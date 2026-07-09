#!/usr/bin/env bash
set -euo pipefail

STACK_NAME="AlbPocStack"
REGION="${AWS_REGION:-us-east-1}"
LOCAL_PORT="${1:-8080}"

if ! command -v session-manager-plugin >/dev/null 2>&1; then
  echo "session-manager-plugin not found on PATH." >&2
  echo "Install it: https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html" >&2
  exit 1
fi

echo "=== ALB POC Connect ==="
echo "Looking up AlbPocStack outputs in $REGION..."

BASTION_ID=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='BastionInstanceId'].OutputValue" \
  --output text)

ALB_DNS=$(aws cloudformation describe-stacks \
  --stack-name "$STACK_NAME" \
  --region "$REGION" \
  --query "Stacks[0].Outputs[?OutputKey=='AlbDnsName'].OutputValue" \
  --output text)

if [[ -z "$BASTION_ID" || -z "$ALB_DNS" ]]; then
  echo "Could not find AlbPocStack outputs. Is the stack deployed? Run ./deploy.sh first." >&2
  exit 1
fi

echo "Bastion:  $BASTION_ID"
echo "ALB DNS:  $ALB_DNS"
echo ""
echo "Opening tunnel: http://localhost:$LOCAL_PORT -> $ALB_DNS:80"
echo "Leave this running, then in another terminal run: ./test-routes.sh $LOCAL_PORT"
echo "Press Ctrl+C to close the tunnel."
echo ""

aws ssm start-session \
  --target "$BASTION_ID" \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters "{\"host\":[\"$ALB_DNS\"],\"portNumber\":[\"80\"],\"localPortNumber\":[\"$LOCAL_PORT\"]}" \
  --region "$REGION"
