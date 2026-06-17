# CDK1

AWS CDK monorepo with two independent stacks:

1. **Cdk1Stack** — Express app on ECS Fargate + Lambda multiply function, behind CloudFront
2. **XrayPocStack** — Disposable X-Ray POC demonstrating end-to-end distributed tracing

---

## Prerequisites

- Node.js 22+
- Python 3.12+
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- Docker (for building container images)

---

## Stack 1: Cdk1Stack

Express app running on ECS Fargate, with a Lambda function for multiplication, served via CloudFront.

**Architecture:**
```
Internet → CloudFront (HTTPS) → ALB (HTTP) → ECS Fargate (Express, port 8000)
                                                  ↓
                                           Lambda (multiply)
```

### Endpoints

- **Health check**: `curl https://d3b9p9zcbknxpt.cloudfront.net/health`
- **Multiply**: `curl -X POST https://d3b9p9zcbknxpt.cloudfront.net/multiply -H "Content-Type: application/json" -d '{"a": 5, "b": 7}'`

> The ALB is internet-facing but its security group restricts inbound traffic to CloudFront IP ranges only (AWS managed prefix list `pl-3b927c52`). Direct ALB access from the public internet is blocked.

### Deploy / Destroy

```bash
./deploy.sh       # Build Lambda + app, deploy CDK stack
./deploy.sh -c    # Clean build (npm ci instead of npm install)
./destroy.sh      # Destroy the stack
./status.sh       # Brief status check
./status.sh -d    # Detailed output with stack events
```

---

## Stack 2: XrayPocStack

Disposable proof-of-concept for AWS X-Ray distributed tracing. Traces a full request chain across Lambda, ECS Fargate, a public API, SNS, and S3.

**Architecture:**
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

### X-Ray instrumentation

- **Lambdas** — X-Ray active tracing + [ADOT Lambda layer](https://aws-otel.github.io/docs/getting-started/lambda) with `AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-handler` for zero-code-change auto-instrumentation
- **ECS Fargate** — AWS OTEL Collector sidecar (`public.ecr.aws/aws-observability/aws-otel-collector`) exporting to X-Ray; app container loads the ADOT Node.js agent via `NODE_OPTIONS`

See [`docs/xray-collector-setup.md`](docs/xray-collector-setup.md) for a full explanation of how both collectors work.

### Deploy / Destroy

```bash
./deploy-xray.sh                                              # Build all components + deploy
cdk destroy XrayPocStack --app "python iac/app_xray.py"      # Destroy the stack
```

### Trigger a trace

After deploying, invoke the invoker Lambda from the AWS Console or CLI:

```bash
aws lambda invoke --function-name xray-invoker /tmp/out.json && cat /tmp/out.json
```

Then view the trace in **AWS Console → X-Ray → Traces** or the **Service Map**.

---

## Repository Structure

```
cdk1/
├── app/                    # Express app for Cdk1Stack (TypeScript)
├── app-xray/               # Express app for XrayPocStack (TypeScript)
├── lambda/
│   ├── multiply/           # Multiply Lambda (Cdk1Stack)
│   ├── xray-invoker/       # Trace trigger Lambda (XrayPocStack)
│   ├── xray-dog-fetcher/   # Dog image fetcher + SNS publisher (XrayPocStack)
│   └── xray-s3-writer/     # SNS-triggered S3 writer (XrayPocStack)
├── iac/
│   ├── cdk1/               # Cdk1Stack definition
│   ├── xray_poc/           # XrayPocStack definition
│   ├── app.py              # CDK entry point for Cdk1Stack
│   └── app_xray.py         # CDK entry point for XrayPocStack
├── docs/
│   └── xray-collector-setup.md
├── deploy.sh               # Deploy Cdk1Stack
├── deploy-xray.sh          # Deploy XrayPocStack
└── destroy.sh              # Destroy Cdk1Stack
```
