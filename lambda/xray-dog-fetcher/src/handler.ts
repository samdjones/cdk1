import { APIGatewayProxyEvent, APIGatewayProxyResult, Context } from "aws-lambda";
import { LambdaClient, InvokeCommand } from "@aws-sdk/client-lambda";

const lambdaClient = new LambdaClient({});
const S3_WRITER_FUNCTION_NAME = process.env.S3_WRITER_FUNCTION_NAME;

interface DogApiResponse {
  message: string;
  status: string;
}

export const handler = async (
  _event: APIGatewayProxyEvent,
  _context: Context
): Promise<APIGatewayProxyResult> => {
  console.log("Fetching random dog image from dog.ceo API");

  const dogApiResponse = await fetch("https://dog.ceo/api/breeds/image/random", {
    method: "GET",
    headers: { Accept: "application/json" },
  });

  if (!dogApiResponse.ok) {
    throw new Error(`dog.ceo API returned status ${dogApiResponse.status}`);
  }

  const dogData: DogApiResponse = (await dogApiResponse.json()) as DogApiResponse;
  const imageUrl = dogData.message;
  const fetchedAt = new Date().toISOString();

  console.log(`Fetched dog image URL: ${imageUrl}`);

  if (!S3_WRITER_FUNCTION_NAME) {
    throw new Error("S3_WRITER_FUNCTION_NAME env var is not set");
  }

  const result = await lambdaClient.send(
    new InvokeCommand({
      FunctionName: S3_WRITER_FUNCTION_NAME,
      InvocationType: "RequestResponse",
      Payload: JSON.stringify({ imageUrl, fetchedAt }),
    })
  );

  if (result.FunctionError) {
    const errorPayload = result.Payload
      ? JSON.parse(Buffer.from(result.Payload).toString("utf-8"))
      : { error: result.FunctionError };
    throw new Error(`s3-writer failed: ${JSON.stringify(errorPayload)}`);
  }

  const writerResult = result.Payload
    ? JSON.parse(Buffer.from(result.Payload).toString("utf-8"))
    : null;

  return {
    statusCode: 200,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ imageUrl, fetchedAt, s3Result: writerResult }),
  };
};
