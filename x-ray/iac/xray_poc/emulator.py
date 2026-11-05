from aws_cdk import aws_ecs as ecs
from constructs import Construct

# Placeholder used only for emulator tests (`cdk ... -c emulator=true`).
EMULATOR_PLACEHOLDER_IMAGE = "public.ecr.aws/docker/library/busybox:latest"


def is_emulator(scope: Construct) -> bool:
    """True during an emulator test (`cdk ... -c emulator=true`)."""
    return bool(scope.node.try_get_context("emulator"))


def is_e2e(scope: Construct) -> bool:
    """True during the local E2E test (`-c emulator=true -c e2e=true`)."""
    return is_emulator(scope) and bool(scope.node.try_get_context("e2e"))


# Floci's container name on the E2E docker network (see ci/e2e_test.sh).
E2E_FLOCI_ENDPOINT = "http://floci-e2e-xray:4566"


def e2e_env(scope: Construct) -> dict:
    """Env that points app containers' AWS SDK at Floci. Empty outside E2E."""
    if not is_e2e(scope):
        return {}
    return {
        "AWS_ENDPOINT_URL": E2E_FLOCI_ENDPOINT,
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_REGION": "us-east-1",
    }


def container_image(scope: Construct, asset_path: str) -> ecs.ContainerImage:
    """Build the image from `asset_path`, except in an emulator test.

    Floci's ECR can't accept image pushes without a Docker daemon, so with
    `-c emulator=true` a placeholder registry image is used instead. Real
    deploys are unaffected.
    """
    if is_e2e(scope):
        # Locally built image (see ci/e2e_test.sh); Floci's ECS uses the
        # local tag instead of pulling, so no ECR push is needed.
        return ecs.ContainerImage.from_registry(
            f"localhost/cdk1-xray-{asset_path.rsplit('/', 1)[-1]}:e2e"
        )
    if is_emulator(scope):
        return ecs.ContainerImage.from_registry(EMULATOR_PLACEHOLDER_IMAGE)
    return ecs.ContainerImage.from_asset(asset_path)
