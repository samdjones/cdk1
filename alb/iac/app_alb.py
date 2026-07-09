#!/usr/bin/env python3
import aws_cdk as cdk
from alb_poc.alb_stack import AlbPocStack

app = cdk.App()

AlbPocStack(
    app,
    "AlbPocStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
    description="ALB POC stack - path-based routing across 3 ECS Fargate backends",
)

app.synth()
