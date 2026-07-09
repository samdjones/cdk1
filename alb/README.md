# ALB POC

Disposable AWS demo of an Application Load Balancer doing path-based routing
across 3 independent ECS Fargate backends.

## What It Does

An internal (not internet-facing) ALB listener routes requests to one of 3
backends by path:

| Path         | Backend   |
| ------------ | --------- |
| `/main/*`    | `main`    |
| `/auth/*`    | `auth`    |
| everything else (`*`) | `default` |

Each backend is a minimal Express app that reports which service handled the
request, so routing is easy to verify with `curl`. The ALB has no public IP
and is not reachable from the internet — the only way in is an SSM
Session Manager port-forward through a small bastion instance, so there's no
need for application-level auth on an otherwise disposable experimental stack.

## Architecture

```
Your laptop
   │  aws ssm start-session (port forward, localhost:8080 → ALB:80)
   ▼
SSM Bastion (EC2, private subnet, zero inbound security group rules)
   │
   ▼
ALB Listener (port 80, internal only — no public IP)
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
- [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
  for the AWS CLI (required for `aws ssm start-session`):
  - macOS: `brew install --cask session-manager-plugin`
  - Linux (Debian/Ubuntu): download and `dpkg -i` the AWS-hosted `.deb`
  - Verify with `session-manager-plugin` — it should print a version banner

## Deploy / Destroy

```bash
./deploy.sh                                                    # Build all 3 apps + deploy
./destroy.sh                                                   # Destroy AlbPocStack
```

The bastion (`t3.nano`) is a small continuous EC2 cost while the stack is
deployed — destroy the stack when you're done with it, as usual.

## Access the ALB

The ALB is internal-only, so reach it via an SSM port-forward through the
bastion. Get `BastionInstanceId` and `AlbDnsName` from the CloudFormation
outputs printed after `./deploy.sh` (or `aws cloudformation describe-stacks
--stack-name AlbPocStack`), then:

```bash
aws ssm start-session --target <bastion-instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<alb-dns>"],"portNumber":["80"],"localPortNumber":["8080"]}' \
  --region us-east-1
```

`--region` is only needed if your AWS CLI's default region isn't already
`us-east-1`. In a second terminal, with the session open:

```bash
curl http://localhost:8080/main/     # {"service":"main", ...}
curl http://localhost:8080/auth/     # {"service":"auth", ...}
curl http://localhost:8080/anything  # {"service":"default", ...}
```

Right after a fresh deploy, the bastion can take under a minute to register
with SSM — retry `start-session` if it fails immediately.

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
