"""
Application Signals wiring shared by the ECS tasks in XrayFrontendStack and
XrayIdpStack. See docs/xray-collector-setup.md.
"""

import json

from aws_cdk import aws_ecs as ecs, aws_iam as iam

# Points the app container's ADOT agent at the CloudWatch Agent sidecar.
APP_SIGNALS_OTEL_ENV = {
    "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
    "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT": "http://localhost:4316/v1/traces",
    "OTEL_AWS_APPLICATION_SIGNALS_EXPORTER_ENDPOINT": "http://localhost:4316/v1/metrics",
    "OTEL_METRICS_EXPORTER": "none",
    "OTEL_LOGS_EXPORTER": "none",
    "OTEL_TRACES_SAMPLER": "xray",
    "OTEL_TRACES_SAMPLER_ARG": "endpoint=http://localhost:2000",
}


def add_cloudwatch_agent_sidecar(
    task_definition: ecs.TaskDefinition,
    container_id: str,
    log_stream_prefix: str,
    app_container: ecs.ContainerDefinition,
) -> ecs.ContainerDefinition:
    """
    Add the CloudWatch Agent sidecar and the task role policy it needs.

    The agent receives the app's OTLP traces and Application Signals metrics
    on port 4316, serves X-Ray sampling rules on TCP port 2000, publishes
    service-level Latency/Error/Fault metrics, and exports the traces to X-Ray.

    The app container is made to wait for this container to start, so the
    app's first sampling-rule fetch and OTLP export don't hit ECONNREFUSED.
    """
    task_definition.task_role.add_managed_policy(
        iam.ManagedPolicy.from_aws_managed_policy_name("CloudWatchAgentServerPolicy")
    )
    container = task_definition.add_container(
        container_id,
        image=ecs.ContainerImage.from_registry(
            "public.ecr.aws/cloudwatch-agent/cloudwatch-agent:latest"
        ),
        environment={
            "CW_CONFIG_CONTENT": json.dumps(
                {
                    "traces": {"traces_collected": {"application_signals": {}}},
                    "logs": {"metrics_collected": {"application_signals": {}}},
                }
            ),
        },
        logging=ecs.LogDrivers.aws_logs(stream_prefix=log_stream_prefix),
        essential=False,
    )
    container.add_port_mappings(ecs.PortMapping(container_port=4316))
    app_container.add_container_dependencies(
        ecs.ContainerDependency(
            container=container,
            condition=ecs.ContainerDependencyCondition.START,
        )
    )
    return container
