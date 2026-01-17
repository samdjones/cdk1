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

Some App tasks are delageted to Lambda functions in the lambda directory.

- `src/handler.ts` - Lambda function handler

### Infrastructure

- `iac/app.py` - CDK app entry point
- `iac/cdk1/cdk1_stack.py` - Stack definition (currently defines an SQS queue)

## Code Style

- ESLint with TypeScript and Prettier integration
- Prettier config: semicolons, double quotes, 2-space tabs, trailing commas (ES5)

## Workflow

- Create feature branches for changes (do not commit directly to main)
- Open PRs for review and merge
