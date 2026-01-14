import { jest } from "@jest/globals";
import request from "supertest";
import app, { setLambdaService, LambdaService } from "../src/app.js";

describe("Multiply endpoint", () => {
  const mockLambdaService: LambdaService = {
    invokeMultiply: jest.fn() as jest.Mock,
  };

  beforeEach(() => {
    jest.clearAllMocks();
    setLambdaService(mockLambdaService);
  });

  afterAll(() => {
    setLambdaService(null);
  });

  it("should return multiplication result", async () => {
    (mockLambdaService.invokeMultiply as jest.Mock).mockResolvedValue({
      result: 12,
    });

    const response = await request(app)
      .post("/multiply")
      .send({ a: 3, b: 4 })
      .set("Content-Type", "application/json");

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ result: 12 });
    expect(mockLambdaService.invokeMultiply).toHaveBeenCalledWith({
      a: 3,
      b: 4,
    });
  });

  it("should handle negative numbers", async () => {
    (mockLambdaService.invokeMultiply as jest.Mock).mockResolvedValue({
      result: -15,
    });

    const response = await request(app)
      .post("/multiply")
      .send({ a: -5, b: 3 })
      .set("Content-Type", "application/json");

    expect(response.status).toBe(200);
    expect(response.body).toEqual({ result: -15 });
  });

  it("should return 400 for missing parameters", async () => {
    const response = await request(app)
      .post("/multiply")
      .send({ a: 3 })
      .set("Content-Type", "application/json");

    expect(response.status).toBe(400);
    expect(response.body).toHaveProperty("error");
  });

  it("should return 400 for non-integer parameters", async () => {
    const response = await request(app)
      .post("/multiply")
      .send({ a: 3.5, b: 2 })
      .set("Content-Type", "application/json");

    expect(response.status).toBe(400);
    expect(response.body.error).toContain("integers");
  });

  it("should return 400 for non-numeric parameters", async () => {
    const response = await request(app)
      .post("/multiply")
      .send({ a: "hello", b: 2 })
      .set("Content-Type", "application/json");

    expect(response.status).toBe(400);
    expect(response.body.error).toContain("numbers");
  });

  it("should handle Lambda invocation errors", async () => {
    (mockLambdaService.invokeMultiply as jest.Mock).mockRejectedValue(
      new Error("Lambda error")
    );

    const response = await request(app)
      .post("/multiply")
      .send({ a: 3, b: 4 })
      .set("Content-Type", "application/json");

    expect(response.status).toBe(500);
    expect(response.body).toHaveProperty("error");
  });
});
