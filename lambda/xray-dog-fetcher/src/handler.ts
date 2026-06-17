import { APIGatewayProxyEvent, APIGatewayProxyResult, Context } from "aws-lambda";
import { SNSClient, PublishCommand } from "@aws-sdk/client-sns";

const snsClient = new SNSClient({});
const DOG_SNS_TOPIC_ARN = process.env.DOG_SNS_TOPIC_ARN;

interface DogApiResponse {
  message: string;
  status: string;
}

export const handler = async (
  _event: APIGatewayProxyEvent,
  _context: Context
): Promise<APIGatewayProxyResult> => {
  console.log("Fetching random dog image from dog.ceo API");

  // Fetch a random dog image from dog.ceo
  const dogApiResponse = await fetch("https://dog.ceo/api/breeds/image/random", {
    method: "GET",
    headers: {
      Accept: "application/json",
    },
  });

  if (!dogApiResponse.ok) {
    throw new Error(`dog.ceo API returned status ${dogApiResponse.status}`);
  }

  const dogData: DogApiResponse = (await dogApiResponse.json()) as DogApiResponse;
  const imageUrl = dogData.message;

  console.log(`Fetched dog image URL: ${imageUrl}`);

  // Publish the image URL to SNS
  if (!DOG_SNS_TOPIC_ARN) {
    throw new Error("DOG_SNS_TOPIC_ARN env var is not set");
  }

  const publishCommand = new PublishCommand({
    TopicArn: DOG_SNS_TOPIC_ARN,
    Message: JSON.stringify({
      imageUrl,
      fetchedAt: new Date().toISOString(),
    }),
    Subject: "Dog image fetched",
  });

  const publishResult = await snsClient.send(publishCommand);
  console.log(`Published to SNS, MessageId: ${publishResult.MessageId}`);

  return {
    statusCode: 200,
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      imageUrl,
      snsMessageId: publishResult.MessageId,
      fetchedAt: new Date().toISOString(),
    }),
  };
};
