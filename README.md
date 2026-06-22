# CDK1 — X-Ray POC

Disposable AWS X-Ray proof-of-concept demonstrating end-to-end distributed tracing across Lambda, ECS Fargate, SNS, and S3.

## What It Does

When triggered, the app fetches a random dog image URL from the [Dog CEO API](https://dog.ceo/dog-api/) and stores it in S3, propagating an X-Ray trace across every hop along the way.

A single trace spans five services: a trigger Lambda kicks off an HTTP call to the ECS-hosted Express app, which invokes a dog-fetcher Lambda that calls the Dog CEO API, publishes the image URL to SNS, which in turn triggers an S3-writer Lambda that persists the URL and metadata to a bucket. The resulting trace is visible as a complete end-to-end service map in the AWS X-Ray console.

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
npm install                                                        # Install aws-cdk dev dep
./deploy.sh                                                        # Build all components + deploy
npx cdk destroy XrayPocStack --app "python iac/app_xray.py"       # Destroy the stack
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
