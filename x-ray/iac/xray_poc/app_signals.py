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

# Exits 0 once the CloudWatch Agent accepts TCP connections on 4316 and 2000.
_WAIT_FOR_PORTS_JS = """
const net = require("net");
const ports = [4316, 2000];
const probe = (port) =>
  new Promise((resolve) => {
    const s = net.connect(port, "127.0.0.1");
    s.on("connect", () => { s.destroy(); resolve(true); });
    s.on("error", () => resolve(false));
  });
(async () => {
  for (let i = 0; i < 120; i++) {
    const ok = await Promise.all(ports.map(probe));
    if (ok.every(Boolean)) { console.log("CloudWatch Agent ready"); return; }
    await new Promise((r) => setTimeout(r, 1000));
  }
  console.error("CloudWatch Agent not ready after 120s");
  process.exit(1);
})();
"""


def add_cloudwatch_agent_sidecar(
    task_definition: ecs.TaskDefinition,
    container_id: str,
    log_stream_prefix: str,
    app_container: ecs.ContainerDefinition,
    app_image: ecs.ContainerImage,
) -> ecs.ContainerDefinition:
    """
    Add the CloudWatch Agent sidecar and the task role policy it needs.

    The agent receives the app's OTLP traces and Application Signals metrics
    on port 4316, serves X-Ray sampling rules on TCP port 2000, publishes
    service-level Latency/Error/Fault metrics, and exports the traces to X-Ray.

    The app container is made to wait until the agent is actually listening on
    ports 4316 and 2000, so the app's first sampling-rule fetch and OTLP export
    don't hit ECONNREFUSED. A `START` dependency isn't enough (the agent's
    ports open a few seconds after its container starts), and the agent image
    has no shell or curl for an ECS health check, so a short-lived init
    container built from the app image polls the ports instead.
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
    wait = task_definition.add_container(
        f"{container_id}Wait",
        image=app_image,
        entry_point=["node", "-e", _WAIT_FOR_PORTS_JS],
        # The image's NODE_OPTIONS would load the OTel agent into this probe.
        environment={"NODE_OPTIONS": ""},
        logging=ecs.LogDrivers.aws_logs(stream_prefix=f"{log_stream_prefix}-wait"),
        essential=False,
    )
    wait.add_container_dependencies(
        ecs.ContainerDependency(
            container=container,
            condition=ecs.ContainerDependencyCondition.START,
        )
    )
    app_container.add_container_dependencies(
        ecs.ContainerDependency(
            container=wait,
            condition=ecs.ContainerDependencyCondition.SUCCESS,
        )
    )
    return container
