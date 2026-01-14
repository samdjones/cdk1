import {
  LambdaClient,
  InvokeCommand,
  InvokeCommandInput,
} from "@aws-sdk/client-lambda";

export interface MultiplyInput {
  a: number;
  b: number;
}

export interface MultiplyResult {
  result: number;
}

export interface LambdaService {
  invokeMultiply(input: MultiplyInput): Promise<MultiplyResult>;
}

export function createLambdaService(
  client: LambdaClient,
  functionName: string
): LambdaService {
  return {
    async invokeMultiply(input: MultiplyInput): Promise<MultiplyResult> {
      const invokeParams: InvokeCommandInput = {
        FunctionName: functionName,
        Payload: Buffer.from(JSON.stringify(input)),
      };

      const command = new InvokeCommand(invokeParams);
      const response = await client.send(command);

      if (response.FunctionError) {
        throw new Error(`Lambda error: ${response.FunctionError}`);
      }

      const payload = Buffer.from(response.Payload!).toString("utf-8");
      return JSON.parse(payload) as MultiplyResult;
    },
  };
}

let defaultService: LambdaService | null = null;

export function getLambdaService(): LambdaService {
  if (!defaultService) {
    const functionName = process.env.MULTIPLY_LAMBDA_NAME;
    if (!functionName) {
      throw new Error("MULTIPLY_LAMBDA_NAME environment variable not set");
    }
    const client = new LambdaClient({});
    defaultService = createLambdaService(client, functionName);
  }
  return defaultService;
}

export function setLambdaService(service: LambdaService | null): void {
  defaultService = service;
}
