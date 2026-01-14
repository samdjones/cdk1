import { Handler } from "aws-lambda";
import { MultiplyInput, MultiplyOutput } from "./types.js";

export const handler: Handler<MultiplyInput, MultiplyOutput> = async (
  event
) => {
  const { a, b } = event;

  if (!Number.isInteger(a) || !Number.isInteger(b)) {
    throw new Error("Both a and b must be integers");
  }

  return {
    result: a * b,
  };
};
