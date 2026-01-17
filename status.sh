#!/bin/bash
set -euo pipefail

STACK_NAME="Cdk1Stack"
DETAILED=false

while getopts "d" opt; do
    case $opt in
        d) DETAILED=true ;;
        *) echo "Usage: $0 [-d]"; echo "  -d  Show detailed output"; exit 1 ;;
    esac
done

STATUS=$(aws cloudformation describe-stacks --stack-name "$STACK_NAME" --query 'Stacks[0].StackStatus' --output text 2>/dev/null) || STATUS="NOT_FOUND"

echo "$STACK_NAME: $STATUS"

if [ "$DETAILED" = true ]; then
    case $STATUS in
        CREATE_COMPLETE|UPDATE_COMPLETE)
            echo ""
            echo "=== Outputs ==="
            aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
                --query 'Stacks[0].Outputs[*].[OutputKey,OutputValue]' \
                --output table
            ;;
        *_IN_PROGRESS)
            echo ""
            echo "=== Recent Events ==="
            aws cloudformation describe-stack-events --stack-name "$STACK_NAME" \
                --query 'StackEvents[:5].[Timestamp,ResourceStatus,ResourceType,LogicalResourceId]' \
                --output table
            ;;
        *_FAILED|ROLLBACK_COMPLETE)
            echo ""
            echo "=== Failed Events ==="
            aws cloudformation describe-stack-events --stack-name "$STACK_NAME" \
                --query 'StackEvents[?ResourceStatus==`CREATE_FAILED` || ResourceStatus==`UPDATE_FAILED`].[Timestamp,ResourceType,LogicalResourceId,ResourceStatusReason]' \
                --output table
            ;;
    esac
fi
