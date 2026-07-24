# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

This repo hosts two independent, disposable AWS CDK demos, each fully self-contained:

- **x-ray/** — end-to-end distributed tracing (X-Ray/OTel) across a Lambda trigger, an Envoy-fronted ECS Fargate app, a second independent ECS Fargate backend reached via CloudMap, two more Lambdas, and S3. Deploys as three CloudFormation stacks (`XraySharedStack`, `XrayIdpStack`, `XrayFrontendStack`).
- **alb/** — an ALB doing path-based routing across 3 ECS Fargate backends (`main`, `auth`, `default`). A single stack (`AlbPocStack`).

Every command below is run from *within* the relevant stack's subdirectory (`x-ray/` or `alb/`), not from the repo root, unless noted otherwise. The repo root only holds a shared `package.json` (the `aws-cdk` CLI devDependency, resolved via `npx` from either subdirectory).

## Commands

### Deploy & Destroy

Each stack has its own deploy/destroy scripts that build its app(s)/lambda(s) and deploy its CDK stack.

```bash
cd x-ray && ./deploy.sh     # Build app-xray + app-idp + 3 lambdas, deploy all 3 stacks (cdk deploy --all)
cd x-ray && ./destroy.sh    # Destroy all 3 stacks (cdk destroy --all)

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
npx cdk synth --app "python app_xray.py"          # or app_alb.py for the alb stack
npx cdk deploy --all --app "python app_xray.py"   # x-ray has 3 stacks; --all deploys them in order
npx cdk diff --all --app "python app_xray.py"
```

## Architecture

### x-ray — XraySharedStack / XrayIdpStack / XrayFrontendStack

A trigger Lambda (`xray-invoker`) calls a shared public ALB, which path-routes `/idp` and `/idp/*` to a `xray-idp` Next.js backend and everything else to a pass-through Envoy sidecar in front of an `xray-frontend` Express app. Before doing its own work, `xray-frontend` makes a best-effort side-call to `xray-idp` over CloudMap (bypassing the ALB), then invokes a `xray-dog-fetcher` Lambda that calls the public Dog CEO API and directly invokes `xray-s3-writer` to persist the result to S3. Every hop is instrumented for distributed tracing, including the Envoy hop itself:

- **Lambdas** — X-Ray active tracing + ADOT Lambda layer (`AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-handler`).
- **ECS Fargate** (`xray-frontend`, `xray-idp`) — AWS OTEL Collector sidecar exporting to X-Ray; each app container loads the ADOT Node.js agent via `NODE_OPTIONS`.
- **Envoy** — pass-through reverse proxy in front of `xray-frontend`, participates in the trace via its native `envoy.tracers.xray` provider.

Deploys as three CloudFormation stacks for learning purposes (a single stack works fine at this scale; the split exists to demonstrate cross-stack CDK patterns):

- **`XraySharedStack`** — VPC (2 AZs, public/private subnets), the public ALB + listener (static default action, no targets), CloudMap private DNS namespace.
- **`XrayIdpStack`** — `xray-idp` cluster/task/service, registered on the shared ALB and in CloudMap. Depends on `XraySharedStack`.
- **`XrayFrontendStack`** — `xray-frontend` cluster/task/service (with Envoy), the 3 Lambda functions, 1 S3 bucket. Depends on `XraySharedStack` and `XrayIdpStack`.

See `x-ray/docs/xray-collector-setup.md` for the full OTel/X-Ray wiring, `x-ray/docs/envoy.md` and `x-ray/docs/cloudmap.md` for those two components, `x-ray/docs/multi-stack.md` for why/how the 3-stack split works, and `x-ray/iac/xray_poc/` (`shared_stack.py`, `idp_stack.py`, `frontend_stack.py`) for the stack definitions.

### alb — AlbPocStack

An internal-only ALB (no public IP, `internet_facing=False`) with one listener routes traffic across 3 independent ECS Fargate backends by path; access is via SSM Session Manager port-forwarding through a small bastion EC2 instance (zero inbound security group rules, `AmazonSSMManagedInstanceCore` role) rather than direct internet access:

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
