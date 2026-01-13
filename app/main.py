from fastapi import FastAPI

app = FastAPI(title="cdk1-app")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
