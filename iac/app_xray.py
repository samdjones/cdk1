#!/usr/bin/env python3
import aws_cdk as cdk
from xray_poc.xray_stack import XrayPocStack

app = cdk.App()

XrayPocStack(
    app,
    "XrayPocStack",
    env=cdk.Environment(
        account=app.node.try_get_context("account"),
        region=app.node.try_get_context("region") or "us-east-1",
    ),
    description="X-Ray POC stack - end-to-end distributed tracing demo",
)

app.synth()
