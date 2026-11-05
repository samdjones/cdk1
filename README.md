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

## Emulator test

Rehearse a deploy against a local [Floci](https://floci.io) AWS emulator before
deploying to real AWS - locally, or in CI, where the **Emulator test**
GitHub workflow runs automatically on every push and PR (and can also be
dispatched manually):

```bash
alb/ci/emulator_test.sh
x-ray/ci/emulator_test.sh
```

Needs `podman` (or `CONTAINER_CLI=docker`). Deploy-and-assert only; no
containers run. For a local-only **E2E test** that runs the real alb app
containers behind the emulated ALB and sends HTTP requests through it:

```bash
alb/ci/e2e_test.sh
```

 See [`x-ray/docs/emulator-test.md`](x-ray/docs/emulator-test.md)
for what's skipped and why.
