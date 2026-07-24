#!/usr/bin/env python3
import aws_cdk as cdk
from xray_poc.shared_stack import XraySharedStack
from xray_poc.idp_stack import XrayIdpStack
from xray_poc.frontend_stack import XrayFrontendStack

app = cdk.App()

env = cdk.Environment(
    account=app.node.try_get_context("account"),
    region=app.node.try_get_context("region") or "us-east-1",
)

shared_stack = XraySharedStack(
    app,
    "XraySharedStack",
    env=env,
    description="X-Ray POC shared infra - VPC, ALB, CloudMap namespace",
)

idp_stack = XrayIdpStack(
    app,
    "XrayIdpStack",
    shared_stack=shared_stack,
    env=env,
    description="X-Ray POC idp backend",
)

frontend_stack = XrayFrontendStack(
    app,
    "XrayFrontendStack",
    shared_stack=shared_stack,
    idp_stack=idp_stack,
    env=env,
    description="X-Ray POC frontend backend - end-to-end distributed tracing demo",
)

app.synth()
