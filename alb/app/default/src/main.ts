import app from "./app.js";

const PORT = parseInt(process.env.PORT ?? "8000", 10);

app.listen(PORT, () => {
  console.log(`${process.env.SERVICE_NAME ?? "default"} server listening on port ${PORT}`);
});
