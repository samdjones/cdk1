# FastAPI app

## Local dev (separate venv)

From this directory:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
pip install -r requirements.txt
pip install -r requirements-dev.txt
python -m uvicorn cdk1_app.main:app --reload
```

App:

- `GET /health`

Run tests:

```bash
pytest
```

## Docker

From this directory:

```bash
docker build -t cdk1-app:local .
docker run --rm -p 8000:8000 cdk1-app:local
```
