# CDK1

AWS CDK project with an Express app running on ECS Fargate and a Lambda function.

# Testing

The application is accessible via CloudFront with HTTPS:
- **Endpoint**: https://d3b9p9zcbknxpt.cloudfront.net
- **Health check**: `curl https://d3b9p9zcbknxpt.cloudfront.net/health`
- **Multiply endpoint**: `curl -X POST https://d3b9p9zcbknxpt.cloudfront.net/multiply -H "Content-Type: application/json" -d '{"a": 5, "b": 7}'`

## Prerequisites

- Node.js 22+
- Python 3.12+
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`)
- Docker (for building container images)
