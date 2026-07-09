# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

This repo hosts two independent, disposable AWS CDK demo stacks, each fully self-contained:

- **x-ray/** — end-to-end distributed tracing (X-Ray/OTel) across a Lambda trigger, an ECS Fargate app, two more Lambdas, and S3.
- **alb/** — an ALB doing path-based routing across 3 ECS Fargate backends (`main`, `auth`, `default`).

Every command below is run from *within* the relevant stack's subdirectory (`x-ray/` or `alb/`), not from the repo root, unless noted otherwise. The repo root only holds a shared `package.json` (the `aws-cdk` CLI devDependency, resolved via `npx` from either subdirectory).

## Commands

### Deploy & Destroy

Each stack has its own deploy/destroy scripts that build its app(s)/lambda(s) and deploy its CDK stack.

```bash
cd x-ray && ./deploy.sh     # Build app-xray + 3 lambdas, deploy XrayPocStack
cd x-ray && ./destroy.sh    # Destroy XrayPocStack

cd alb && ./deploy.sh       # Build main/auth/default apps, deploy AlbPocStack
cd alb && ./destroy.sh      # Destroy AlbPocStack
```

### App(s) (TypeScript/Express)

Run from the relevant app directory, e.g. `x-ray/app-xray/` or `alb/app/main/`:

```bash
npm install    # Install dependencies
npm run dev    # Run development server with ts-node
npm run build  # Compile TypeScript to dist/
```

Docker build (requires `npm run build` first), e.g. for `x-ray/app-xray/`:
```bash
docker build -t cdk1-app:local .
docker run --rm -p 8000:8000 cdk1-app:local
```

### Lambda (TypeScript, x-ray only)

Run from each lambda directory under `x-ray/lambda/` (`xray-invoker/`, `xray-dog-fetcher/`, `xray-s3-writer/`):

```bash
npm install    # Install dependencies
npm run build  # Compile TypeScript to dist/
```

### Infrastructure (CDK/Python)

Run from each stack's own `iac/` directory (`x-ray/iac/` or `alb/iac/`), each with its own `.venv`:

```bash
source .venv/bin/activate
pip install -r requirements.txt
npx cdk synth --app "python app_xray.py"   # or app_alb.py for the alb stack
npx cdk deploy --app "python app_xray.py"
npx cdk diff --app "python app_xray.py"
```

## Architecture

### x-ray — XrayPocStack

A trigger Lambda (`xray-invoker`) makes an HTTP call to an ECS Fargate Express app, which invokes a `xray-dog-fetcher` Lambda that calls the public Dog CEO API and then directly invokes `xray-s3-writer` to persist the result to S3. Every hop is instrumented for distributed tracing:

- **Lambdas** — X-Ray active tracing + ADOT Lambda layer (`AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-handler`).
- **ECS Fargate** — AWS OTEL Collector sidecar exporting to X-Ray; app container loads the ADOT Node.js agent via `NODE_OPTIONS`.
- **Components**: VPC (2 AZs, public/private subnets), ECS cluster + Fargate service behind a public ALB (`ecs_patterns.ApplicationLoadBalancedFargateService`, fully public — no CloudFront), 3 Lambda functions, 1 S3 bucket.

See `x-ray/docs/xray-collector-setup.md` for the full OTel/X-Ray wiring, and `x-ray/iac/xray_poc/xray_stack.py` for the stack definition.

### alb — AlbPocStack

A single public ALB with one listener routes traffic across 3 independent ECS Fargate backends by path:

- `/main/*` → `main` backend
- `/auth/*` → `auth` backend
- `*` (everything else) → `default` backend (the listener's default action)

No tracing/Lambda/S3 in this stack — it's focused purely on demonstrating ALB path-based routing. See `alb/iac/alb_poc/alb_stack.py`.

## Code Style

- ESLint with TypeScript and Prettier integration where configured
- Prettier config: semicolons, double quotes, 2-space tabs, trailing commas (ES5)

## Workflow

- Create feature branches for changes (do not commit directly to main)
- Open PRs for review and merge
