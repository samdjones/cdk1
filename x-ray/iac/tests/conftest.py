"""Emulator-test fixtures: assertions run against stacks deployed into Floci.

Run via ``x-ray/ci/emulator_test.sh`` (starts Floci, deploys, then calls pytest).
"""

import os

import boto3
import pytest

SHARED = "XraySharedStack"
IDP = "XrayIdpStack"
FRONTEND = "XrayFrontendStack"


def pytest_configure(config):
    # Never let these tests talk to real AWS: they assume a local emulator.
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    if "localhost" not in endpoint and "127.0.0.1" not in endpoint:
        pytest.exit(
            "AWS_ENDPOINT_URL must point at the local Floci emulator "
            f"(got {endpoint!r}). Run x-ray/ci/emulator_test.sh instead.",
            returncode=2,
        )


def _client(name):
    return pytest.fixture(scope="session")(lambda: boto3.client(name))


cfn = _client("cloudformation")
elbv2 = _client("elbv2")
ecs = _client("ecs")
ec2 = _client("ec2")
lambda_ = _client("lambda")
s3 = _client("s3")
servicediscovery = _client("servicediscovery")


@pytest.fixture(scope="session")
def resources_of_type(cfn):
    """Return a function: (stack, CloudFormation type) -> physical ids."""

    def lookup(stack, resource_type):
        resources = cfn.describe_stack_resources(StackName=stack)["StackResources"]
        return [
            r["PhysicalResourceId"]
            for r in resources
            if r["ResourceType"] == resource_type
        ]

    return lookup
