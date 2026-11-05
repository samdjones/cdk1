"""Emulator-test fixtures: assertions run against stacks deployed into Floci.

Run via ``alb/ci/emulator_test.sh`` (starts Floci, deploys, then calls pytest).
"""

import os

import boto3
import pytest

STACK_NAME = "AlbPocStack"


def pytest_configure(config):
    # Never let these tests talk to real AWS: they assume a local emulator.
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "")
    if "localhost" not in endpoint and "127.0.0.1" not in endpoint:
        pytest.exit(
            "AWS_ENDPOINT_URL must point at the local Floci emulator "
            f"(got {endpoint!r}). Run alb/ci/emulator_test.sh instead.",
            returncode=2,
        )


@pytest.fixture(scope="session")
def ecs():
    return boto3.client("ecs")


@pytest.fixture(scope="session")
def ec2():
    return boto3.client("ec2")


@pytest.fixture(scope="session")
def cfn():
    return boto3.client("cloudformation")


@pytest.fixture(scope="session")
def elbv2():
    return boto3.client("elbv2")


@pytest.fixture(scope="session")
def resources_of_type(cfn):
    """Return a function: CloudFormation type -> physical ids in AlbPocStack."""
    resources = cfn.describe_stack_resources(StackName=STACK_NAME)["StackResources"]

    def lookup(resource_type):
        return [
            r["PhysicalResourceId"]
            for r in resources
            if r["ResourceType"] == resource_type
        ]

    return lookup


@pytest.fixture(scope="session")
def alb_arn(resources_of_type):
    (arn,) = resources_of_type("AWS::ElasticLoadBalancingV2::LoadBalancer")
    return arn
