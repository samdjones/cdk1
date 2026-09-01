import { APIGatewayProxyEvent, APIGatewayProxyResult, Context } from "aws-lambda";

const FRONTEND_URL = process.env.FRONTEND_URL;

if (!FRONTEND_URL) {
  console.warn("FRONTEND_URL env var not set");
}

export const handler = async (
  _event: APIGatewayProxyEvent,
  _context: Context
): Promise<APIGatewayProxyResult> => {
  const url = FRONTEND_URL ?? "http://localhost:8000/fetch-dog";

  console.log(`Invoking frontend at: ${url}`);

  const response = await fetch(url, {
    method: "GET",
    headers: {
      "Content-Type": "application/json",
    },
  });

  const body = await response.text();

  console.log(`Frontend responded with status: ${response.status}`);
  console.log(`Response body: ${body}`);

  if (!response.ok) {
    throw new Error(`Frontend returned ${response.status}: ${body}`);
  }

  return {
    statusCode: response.status,
    headers: {
      "Content-Type": "application/json",
    },
    body,
  };
};
