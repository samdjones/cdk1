import { handler } from "../src/handler.js";
import { Context, Callback } from "aws-lambda";
import { MultiplyOutput } from "../src/types.js";

const mockContext = {} as Context;
const mockCallback: Callback<MultiplyOutput> = () => {};

describe("multiply handler", () => {
  it("should multiply two positive integers", async () => {
    const result = await handler({ a: 3, b: 4 }, mockContext, mockCallback);
    expect(result).toEqual({ result: 12 });
  });

  it("should handle negative integers", async () => {
    const result = await handler({ a: -5, b: 3 }, mockContext, mockCallback);
    expect(result).toEqual({ result: -15 });
  });

  it("should handle zero", async () => {
    const result = await handler({ a: 0, b: 100 }, mockContext, mockCallback);
    expect(result).toEqual({ result: 0 });
  });

  it("should handle large numbers", async () => {
    const result = await handler(
      { a: 1000000, b: 1000000 },
      mockContext,
      mockCallback
    );
    expect(result).toEqual({ result: 1000000000000 });
  });

  it("should throw error for non-integer input", async () => {
    await expect(
      handler({ a: 3.5, b: 2 }, mockContext, mockCallback)
    ).rejects.toThrow("Both a and b must be integers");
  });
});
