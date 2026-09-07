# X-Ray POC

Disposable AWS X-Ray proof-of-concept demonstrating end-to-end distributed tracing across Lambda, ECS Fargate (behind an Envoy sidecar and a path-routing ALB), CloudMap service discovery, and S3.

## What It Does

When triggered, the app fetches a random dog image URL from the [Dog CEO API](https://dog.ceo/dog-api/) and stores it in S3, propagating an X-Ray trace across every hop along the way — including through an Envoy proxy and a side-call to a second, independent backend service.

A trigger Lambda kicks off an HTTP call to a shared ALB, which path-routes to an Envoy sidecar in front of the ECS-hosted Express app (`xray-frontend`). Before doing anything else, the app makes a side-call to a second ECS service (`xray-idp`, a minimal Next.js app) over its private CloudMap DNS name, then invokes a dog-fetcher Lambda that calls the Dog CEO API and invokes an S3-writer Lambda directly to persist the URL and metadata to a bucket. The resulting trace is visible as a complete end-to-end service map in the AWS X-Ray console — including the Envoy hop and the idp side-call, both of which take deliberate extra wiring to show up at all (see the docs linked below).

## Architecture

```
xray-invoker Lambda  (trigger from console)
        ↓  HTTP, via the shared ALB
Envoy sidecar  (pass-through, participates in the X-Ray trace)
        ↓
ECS Fargate frontend  (xray-frontend, Node.js Express)
        │
        ├─ side-call, via CloudMap (idp.xray.local) ─→  ECS Fargate idp  (xray-idp, Next.js)
        │
        ↓  Lambda invoke
xray-dog-fetcher Lambda
        ↓  fetch
dog.ceo public API  (random dog image URL)
        ↓  Lambda invoke (synchronous)
xray-s3-writer Lambda
        ↓  PutObject
S3 Bucket  (image + metadata JSON)
```

The shared ALB path-routes `/idp` and `/idp/*` to `xray-idp` and everything else to `xray-frontend` (via Envoy) — that's the public entry point into either service. The side-call above is a *separate*, private path: `xray-frontend` reaches `xray-idp` directly over CloudMap, bypassing the ALB.

Every hop from the invoker down through S3 is synchronous end-to-end, so a failure at any point (e.g. a misconfigured `DOG_BUCKET_NAME`) propagates back as an error through the entire chain — making it immediately visible as a red node in the X-Ray service map and as a non-200 response from the invoker. The idp side-call is the one exception: it's best-effort, logged but non-fatal, so an idp outage doesn't take down dog-fetching.

## X-Ray Instrumentation

- **Lambdas** — X-Ray active tracing + `AWSOpenTelemetryDistroJs` Lambda layer with `AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument` (Application Signals off — plain X-Ray export only)
- **ECS Fargate** (`xray-frontend`, `xray-idp`) — AWS OTEL Collector sidecar exporting to X-Ray; each app loads the ADOT Node.js agent via `NODE_OPTIONS`
- **Envoy** — native `envoy.tracers.xray` provider, sending segments to the OTEL collector's UDP X-Ray-daemon receiver — see [`docs/envoy.md`](docs/envoy.md)

See [`docs/xray-collector-setup.md`](docs/xray-collector-setup.md) for the full instrumentation writeup, [`docs/envoy.md`](docs/envoy.md) for the Envoy sidecar, and [`docs/cloudmap.md`](docs/cloudmap.md) for the CloudMap service discovery setup behind the idp side-call.

## Stacks

Despite being one demo, this deploys as three CloudFormation stacks instead of one:

- **`XraySharedStack`** — VPC, the shared ALB (listener only, no targets), CloudMap namespace
- **`XrayIdpStack`** — the `xray-idp` cluster/task/service, registered on the ALB and in CloudMap
- **`XrayFrontendStack`** — the `xray-frontend` cluster/task/service, the three Lambdas, S3

`XrayIdpStack` depends on `XraySharedStack`; `XrayFrontendStack` depends on both. `cdk deploy --all`/`cdk destroy --all` (what `deploy.sh`/`destroy.sh` use) handle the ordering automatically. This split exists for learning purposes — see [`docs/multi-stack.md`](docs/multi-stack.md) for why it's structured this way and the non-obvious CDK mechanics a shared ALB across stacks requires.

## Prerequisites

- Node.js 22+
- Python 3.12+
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- Docker

## Deploy / Destroy

```bash
npm install                                                          # Install aws-cdk dev dep
./deploy.sh                                                          # Build all components + deploy all 3 stacks
npx cdk destroy --all --app "python iac/app_xray.py"                # Destroy all 3 stacks
```

## Trigger a Trace

```bash
./trigger-trace.sh
```

Then view results in **AWS Console → X-Ray → Traces** or **Service Map**.

## Repository Structure

```
x-ray/
├── app-xray/               # ECS Fargate Express app (xray-frontend)
├── app-idp/                # ECS Fargate Next.js app (xray-idp)
├── envoy/                  # Pass-through Envoy sidecar in front of xray-frontend
├── lambda/
│   ├── xray-invoker/       # Trace trigger (HTTP → ALB → Envoy → ECS)
│   ├── xray-dog-fetcher/   # Fetches dog image, invokes s3-writer
│   └── xray-s3-writer/     # Writes image to S3
├── iac/
│   ├── xray_poc/
│   │   ├── shared_stack.py   # XraySharedStack: VPC, ALB, CloudMap namespace
│   │   ├── idp_stack.py      # XrayIdpStack
│   │   └── frontend_stack.py # XrayFrontendStack
│   └── app_xray.py         # CDK entry point (instantiates all 3 stacks)
├── ci/
│   ├── docker_build.sh
│   └── run_unit_tests.sh
├── docs/
│   ├── xray-collector-setup.md
│   ├── envoy.md
│   ├── cloudmap.md
│   └── multi-stack.md
├── deploy.sh
├── destroy.sh
└── trigger-trace.sh
```

All commands in this README are run from within this `x-ray/` directory unless noted otherwise. This demo shares the repo-root `package.json` (the `aws-cdk` CLI devDependency, used via `npx`) with the sibling `alb/` demo — see the [repo root README](../README.md).
