# CDK1

AWS CDK project with an Express app running on ECS Fargate and a Lambda function.

## Quick Start

### Deploy

```bash
./deploy.sh      # Fast mode: keeps node_modules, uses npm install
./deploy.sh -c   # Clean mode: deletes node_modules, uses npm ci
```

The deploy script:
1. Builds the Lambda function (`lambda/multiply`)
2. Builds the Express app (`app/`)
3. Deploys the CDK stack (creates VPC, ECS cluster, Fargate service, Lambda, ALB)

### Destroy

```bash
./destroy.sh     # Destroys the entire CDK stack
```

### Status

```bash
./status.sh      # Brief status check
./status.sh -d   # Detailed output with stack outputs/events
```

## Project Structure

- **app/** - TypeScript/Express HTTP server (Node.js 22)
- **lambda/multiply/** - TypeScript Lambda function
- **iac/** - AWS CDK infrastructure (Python)
- **ci/** - CI scripts for testing and Docker builds

## Prerequisites

- Node.js 22+
- Python 3.12+
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- Docker (for building container images)
