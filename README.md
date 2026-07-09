# cdk1 — CDK Demos

Two independent, disposable AWS CDK demo stacks:

- **[`x-ray/`](x-ray/README.md)** — end-to-end distributed tracing (X-Ray) across
  Lambda, ECS Fargate, and S3.
- **[`alb/`](alb/README.md)** — ALB path-based routing across 3 ECS Fargate
  backends (`main`, `auth`, `default`).

Each demo is self-contained: its own `iac/` (CDK app), app(s)/lambda(s), `ci/`
scripts, and `deploy.sh` / `destroy.sh`. See each subdirectory's README for
setup and usage.

## Shared

- Root `package.json` holds the `aws-cdk` CLI as a shared devDependency, used
  via `npx cdk ...` by both stacks' `deploy.sh` / `destroy.sh`.
