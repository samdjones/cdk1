import express, { Application, Request, Response } from "express";

const app: Application = express();

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok" });
});

export default app;
