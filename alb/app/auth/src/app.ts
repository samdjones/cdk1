import express, { Request, Response } from "express";

const app = express();
app.use(express.json());

const SERVICE_NAME = process.env.SERVICE_NAME ?? "auth";

app.get("/health", (_req: Request, res: Response) => {
  res.json({ status: "ok", service: SERVICE_NAME });
});

app.get("*", (req: Request, res: Response) => {
  res.json({ service: SERVICE_NAME, path: req.path });
});

export default app;
