# ALB POC

Disposable AWS demo of an Application Load Balancer doing path-based routing
across 3 independent ECS Fargate backends.

## What It Does

A single public ALB listener routes requests to one of 3 backends by path:

| Path         | Backend   |
| ------------ | --------- |
| `/main/*`    | `main`    |
| `/auth/*`    | `auth`    |
| everything else (`*`) | `default` |

Each backend is a minimal Express app that reports which service handled the
request, so routing is easy to verify with `curl`.

## Architecture

```
Internet
   │
   ▼
ALB Listener (port 80)
   ├── /main/*  ──▶  main backend    (ECS Fargate)
   ├── /auth/*  ──▶  auth backend    (ECS Fargate)
   └── *        ──▶  default backend (ECS Fargate, listener default action)
```

No tracing, Lambda, or S3 — this demo is focused purely on ALB path-based
routing.

## Prerequisites

- Node.js 22+
- Python 3.12+
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`, or via the shared root `package.json`)
- Docker

## Deploy / Destroy

```bash
./deploy.sh                                                    # Build all 3 apps + deploy
./destroy.sh                                                   # Destroy AlbPocStack
```

## Try the Routing

```bash
curl http://<alb-dns>/main/     # {"service":"main", ...}
curl http://<alb-dns>/auth/     # {"service":"auth", ...}
curl http://<alb-dns>/anything  # {"service":"default", ...}
```

`<alb-dns>` is printed as the `AlbDnsName` CloudFormation output after deploy.

## Repository Structure

```
alb/
├── app/
│   ├── main/       # ECS Fargate backend for /main/*
│   ├── auth/       # ECS Fargate backend for /auth/*
│   └── default/    # ECS Fargate backend for everything else
├── iac/
│   ├── alb_poc/    # AlbPocStack CDK definition
│   └── app_alb.py  # CDK entry point
├── ci/
│   ├── docker_build.sh
│   └── run_unit_tests.sh
├── deploy.sh
└── destroy.sh
```

This demo shares the repo-root `package.json` (the `aws-cdk` CLI
devDependency, used via `npx`) with the sibling `x-ray/` demo — see the
[repo root README](../README.md).
