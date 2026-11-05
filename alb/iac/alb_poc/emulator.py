from aws_cdk import aws_ecs as ecs
from constructs import Construct

# Placeholder used only for emulator tests (`cdk ... -c emulator=true`).
EMULATOR_PLACEHOLDER_IMAGE = "public.ecr.aws/docker/library/busybox:latest"


def is_emulator(scope: Construct) -> bool:
    """True during an emulator test (`cdk ... -c emulator=true`)."""
    return bool(scope.node.try_get_context("emulator"))


def container_image(scope: Construct, asset_path: str) -> ecs.ContainerImage:
    """Build the image from `asset_path`, except in an emulator test.

    Floci's ECR can't accept image pushes without a Docker daemon, so with
    `-c emulator=true` a placeholder registry image is used instead. Real
    deploys are unaffected.
    """
    if is_emulator(scope) and scope.node.try_get_context("e2e"):
        # Locally built image (see ci/e2e_test.sh); Floci's ECS uses the
        # local tag when the registry pull fails, so no ECR push is needed.
        return ecs.ContainerImage.from_registry(
            f"localhost/cdk1-alb-{asset_path.rsplit('/', 1)[-1]}:e2e"
        )
    if is_emulator(scope):
        return ecs.ContainerImage.from_registry(EMULATOR_PLACEHOLDER_IMAGE)
    return ecs.ContainerImage.from_asset(asset_path)
