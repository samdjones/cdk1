import express, { Application, Request, Response } from "express";
import {
  getLambdaService,
  setLambdaService,
  LambdaService,
} from "./services/lambdaService.js";

const app: Application = express();

app.use(express.json());

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok" });
});

interface MultiplyRequestBody {
  a: number;
  b: number;
}

app.post("/multiply", async (req: Request, res: Response) => {
  try {
    const { a, b } = req.body as MultiplyRequestBody;

    if (typeof a !== "number" || typeof b !== "number") {
      res.status(400).json({ error: "Both 'a' and 'b' must be numbers" });
      return;
    }

    if (!Number.isInteger(a) || !Number.isInteger(b)) {
      res.status(400).json({ error: "Both 'a' and 'b' must be integers" });
      return;
    }

    const lambdaService = getLambdaService();
    const result = await lambdaService.invokeMultiply({ a, b });

    res.json(result);
  } catch (error) {
    console.error("Error invoking multiply Lambda:", error);
    res.status(500).json({ error: "Internal server error" });
  }
});

export { setLambdaService };
export type { LambdaService };
export default app;
