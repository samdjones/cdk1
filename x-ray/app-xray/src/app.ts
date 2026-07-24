import express, { Request, Response } from "express";
import { LambdaClient, InvokeCommand } from "@aws-sdk/client-lambda";

const app = express();
app.use(express.json());

const lambdaClient = new LambdaClient({});
const DOG_FETCHER_LAMBDA_NAME = process.env.DOG_FETCHER_LAMBDA_NAME;
const IDP_URL = process.env.IDP_URL;

// Best-effort side-call to idp over its private CloudMap DNS name - not a
// readiness gate, just an observable hop in the trace before the real
// backend calls. A failure here is logged but doesn't fail the request.
async function checkIdpHealth(): Promise<void> {
  if (!IDP_URL) {
    return;
  }
  try {
    const response = await fetch(`${IDP_URL}/idp/health`);
    console.log(`idp health check: ${response.status}`);
  } catch (err) {
    console.error("idp health check failed:", err);
  }
}

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok" });
});

app.get("/fetch-dog", async (_req: Request, res: Response) => {
  if (!DOG_FETCHER_LAMBDA_NAME) {
    res.status(500).json({ error: "DOG_FETCHER_LAMBDA_NAME env var not set" });
    return;
  }

  await checkIdpHealth();

  console.log(`Invoking Lambda: ${DOG_FETCHER_LAMBDA_NAME}`);

  try {
    const command = new InvokeCommand({
      FunctionName: DOG_FETCHER_LAMBDA_NAME,
      InvocationType: "RequestResponse",
      Payload: JSON.stringify({}),
    });

    const result = await lambdaClient.send(command);

    if (result.FunctionError) {
      console.error(`Lambda function error: ${result.FunctionError}`);
      const errorPayload = result.Payload
        ? JSON.parse(Buffer.from(result.Payload).toString("utf-8"))
        : { error: result.FunctionError };
      res.status(502).json({ error: "Lambda invocation failed", details: errorPayload });
      return;
    }

    const payload = result.Payload
      ? JSON.parse(Buffer.from(result.Payload).toString("utf-8"))
      : null;

    console.log(`Lambda responded with status: ${result.StatusCode}`);

    // Lambda returns an APIGatewayProxyResult; unwrap the body
    if (payload && typeof payload === "object" && "body" in payload) {
      const body =
        typeof payload.body === "string" ? JSON.parse(payload.body) : payload.body;
      res.status(payload.statusCode ?? 200).json(body);
    } else {
      res.json(payload);
    }
  } catch (err) {
    console.error("Error invoking Lambda:", err);
    res.status(500).json({ error: "Internal server error", message: String(err) });
  }
});

export default app;
