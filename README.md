# CDK1 — X-Ray POC

Disposable AWS X-Ray proof-of-concept demonstrating end-to-end distributed tracing across Lambda, ECS Fargate, SNS, and S3.

## Architecture

```
xray-invoker Lambda  (trigger from console)
        ↓  HTTP
ECS Fargate frontend  (Node.js Express)
        ↓  Lambda invoke
xray-dog-fetcher Lambda
        ↓  fetch
dog.ceo public API  (random dog image URL)
        ↓  SNS publish
SNS Topic
        ↓  trigger
xray-s3-writer Lambda
        ↓  PutObject
S3 Bucket  (image + metadata JSON)
```

Every hop produces X-Ray trace segments that stitch into a single end-to-end trace visible in the X-Ray service map.

## X-Ray Instrumentation

- **Lambdas** — X-Ray active tracing + ADOT Lambda layer with `AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-handler`
- **ECS Fargate** — AWS OTEL Collector sidecar exporting to X-Ray; app loads ADOT Node.js agent via `NODE_OPTIONS`

See [`docs/xray-collector-setup.md`](docs/xray-collector-setup.md) for a full explanation.

## Prerequisites

- Node.js 22+
- Python 3.12+
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- Docker

## Deploy / Destroy

```bash
./deploy.sh                                          # Build all components + deploy
cdk destroy XrayPocStack --app "python iac/app_xray.py"   # Destroy the stack
```

## Trigger a Trace

```bash
aws lambda invoke --function-name xray-invoker /tmp/out.json && cat /tmp/out.json
```

Then view results in **AWS Console → X-Ray → Traces** or **Service Map**.

## Repository Structure

```
cdk1/
├── app-xray/               # ECS Fargate Express app
├── lambda/
│   ├── xray-invoker/       # Trace trigger (HTTP → ECS)
│   ├── xray-dog-fetcher/   # Fetches dog image, publishes to SNS
│   └── xray-s3-writer/     # SNS-triggered, writes image to S3
├── iac/
│   ├── xray_poc/           # XrayPocStack CDK definition
│   └── app_xray.py         # CDK entry point
├── docs/
│   └── xray-collector-setup.md
└── deploy.sh
```
