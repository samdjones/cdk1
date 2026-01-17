# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Structure

This is a monorepo with main component directories:
- **app/** - TypeScript/Express HTTP server (Node.js 22)
- **lambda/** - TypeScript Lambda functions (Node.js 22)
- **iac/** - AWS CDK infrastructure (Python)
- **ci/** - CI scripts for testing and Docker builds

## Commands

### Deploy & Destroy

The deploy script builds Lambda and App, then deploys the CDK stack.

```bash
./deploy.sh      # Fast mode: keeps node_modules, uses npm install
./deploy.sh -c   # Clean mode: deletes node_modules, uses npm ci
./destroy.sh     # Destroys the entire CDK stack
./status.sh      # Brief status check
./status.sh -d   # Detailed output with stack outputs/events
```

### App (TypeScript/Express)

All commands run from the `app/` directory:

```bash
npm install          # Install dependencies
npm run dev          # Run development server with ts-node
npm run build        # Compile TypeScript to dist/
npm test             # Run Jest tests (uses experimental VM modules)
npm run lint         # Run ESLint
npm run lint:fix     # Run ESLint with auto-fix
npm run format       # Format code with Prettier
npm run format:check # Check formatting
```

Run a single test file:
```bash
npm test -- tests/health.test.ts
```

Docker build (requires `npm run build` first):
```bash
docker build -t cdk1-app:local .
docker run --rm -p 8000:8000 cdk1-app:local
```

### Lambda (TypeScript)

All commands run from the `lambda/multiply/` directory:

```bash
npm install          # Install dependencies
npm run build        # Compile TypeScript to dist/
npm test             # Run Jest tests (uses experimental VM modules)
```

### Infrastructure (CDK/Python)

All commands run from the `iac/` directory:

```bash
source .venv/bin/activate
pip install -r requirements.txt
cdk synth            # Synthesize CloudFormation template
cdk deploy           # Deploy stack
cdk diff             # Compare deployed vs current
```

## Architecture

### App

This is the entrypoint to the app.

- `src/app.ts` - Express application setup and route definitions (exported for testing)
- `src/main.ts` - Server entry point, starts listening on PORT env var (default 8000)
- `tests/` - Jest tests using supertest for HTTP testing
- Uses ES modules (`"type": "module"` in package.json)

### Lambda/Multiply

Some App tasks are delegated to Lambda functions in the lambda directory.

- `src/handler.ts` - Lambda function handler

### Infrastructure

- `iac/app.py` - CDK app entry point
- `iac/cdk1/cdk1_stack.py` - Stack definition (VPC, ECS Cluster, Fargate service with ALB, Lambda function, CloudFront distribution)

**Architecture Flow:**
```
Internet → CloudFront (HTTPS:443) → ALB (HTTP:80, public) → Fargate (HTTP:8000)
```

**Components:**
- VPC with public/private subnets across 2 AZs
- ECS Fargate service running Express app (container port 8000)
- Application Load Balancer (internet-facing, security group restricted)
- CloudFront distribution (HTTPS endpoint)
- Lambda function for multiplication operations
- Security groups for network access control

## Security Architecture

### CloudFront + ALB Security Model

The application uses a defense-in-depth approach:

1. **CloudFront as Primary Entry Point**
   - HTTPS-only access (HTTP redirected to HTTPS)
   - Single public endpoint: `https://d3b9p9zcbknxpt.cloudfront.net`
   - Connects to ALB origin via HTTP (AWS private network)

2. **ALB Security Group Restriction**
   - ALB is internet-facing but security group limits access to CloudFront only
   - Uses AWS managed prefix list `pl-3b927c52` (CloudFront IP ranges)
   - Configuration: `open_listener=False` prevents default 0.0.0.0/0 rule
   - Direct public internet access to ALB is blocked

3. **ECS Tasks in Private Subnets**
   - Fargate tasks run in private subnets
   - Only accessible via ALB
   - No direct internet access to containers

**Key Security Files:**
- `iac/cdk1/cdk1_stack.py:49` - `open_listener=False` configuration
- `iac/cdk1/cdk1_stack.py:55-60` - CloudFront prefix list security group rule

**Testing Security:**
- ✅ CloudFront access works: `curl https://d3b9p9zcbknxpt.cloudfront.net/health`
- ❌ Direct ALB access blocked: `curl http://<alb-dns>/health` (times out)

## Code Style

- ESLint with TypeScript and Prettier integration
- Prettier config: semicolons, double quotes, 2-space tabs, trailing commas (ES5)

## Workflow

- Create feature branches for changes (do not commit directly to main)
- Open PRs for review and merge
