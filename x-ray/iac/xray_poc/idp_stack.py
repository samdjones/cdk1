from aws_cdk import (
    Stack,
    Duration,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
    aws_iam as iam,
    aws_servicediscovery as servicediscovery,
)
from constructs import Construct

from xray_poc.shared_stack import XraySharedStack


class XrayIdpStack(Stack):
    """
    The xray-idp backend: its own ECS cluster, task, and service, registered
    both on the shared ALB (for the public /idp, /idp/* paths) and in
    CloudMap (for XrayFrontendStack's private side-call). No Envoy sidecar.

    Depends on XraySharedStack for the VPC, the ALB listener, and the
    CloudMap namespace - all read-only cross-stack references, no mutation
    of anything SharedStack owns.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        shared_stack: XraySharedStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.container_port = 3000
        self.cloud_map_name = "idp"

        # ── ECS Cluster ────────────────────────────────────────────────────
        cluster = ecs.Cluster(
            self,
            "XrayIdpCluster",
            vpc=shared_stack.vpc,
            container_insights=True,
        )

        # ── ECS Task Definition ──────────────────────────────────────────────
        task_definition = ecs.FargateTaskDefinition(
            self,
            "XrayIdpTaskDef",
            cpu=512,
            memory_limit_mib=1024,
        )

        task_definition.task_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                    "xray:GetSamplingStatisticSummaries",
                ],
                resources=["*"],
            )
        )

        app_container = task_definition.add_container(
            "IdpAppContainer",
            image=ecs.ContainerImage.from_asset("app-idp"),
            environment={
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
                "OTEL_SERVICE_NAME": "xray-idp",
                "OTEL_PROPAGATORS": "xray",
                "AWS_XRAY_DAEMON_ADDRESS": "localhost:2000",
                "OTEL_AWS_APPLICATION_SIGNALS_ENABLED": "true",
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="xray-idp-app"),
            essential=True,
        )
        app_container.add_port_mappings(ecs.PortMapping(container_port=self.container_port))

        otel_container = task_definition.add_container(
            "IdpOtelCollector",
            image=ecs.ContainerImage.from_registry(
                "public.ecr.aws/aws-observability/aws-otel-collector:latest"
            ),
            command=["--config=/etc/ecs/ecs-default-config.yaml"],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="xray-idp-otel"),
            essential=False,
            environment={
                "AWS_REGION": Stack.of(self).region,
            },
        )
        otel_container.add_port_mappings(ecs.PortMapping(container_port=4317))
        otel_container.add_port_mappings(ecs.PortMapping(container_port=4318))

        # ── ECS Service ──────────────────────────────────────────────────────
        service = ecs.FargateService(
            self,
            "XrayIdpService",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            cloud_map_options=ecs.CloudMapOptions(
                name=self.cloud_map_name,
                cloud_map_namespace=shared_stack.cloud_map_namespace,
                dns_record_type=servicediscovery.DnsRecordType.A,
                container_port=self.container_port,
            ),
            health_check_grace_period=Duration.seconds(60),
        )

        # Exposed for XrayFrontendStack's cross-stack ingress rule - it needs
        # to reach this service directly via CloudMap, bypassing the ALB.
        self.security_group = service.connections.security_groups[0]

        # ── ALB registration ─────────────────────────────────────────────────
        # A locally-scoped, imported reference to the ALB's security group -
        # not the real shared_stack.alb_security_group object. This stack
        # already depends on SharedStack (VPC, namespace, listener ARN), so
        # any resource CDK creates that references SharedStack *back* would
        # be a direct cycle. Passing the real object here does exactly that:
        # CDK's automatic ALB<->target SG-pairing adds a new rule *inside
        # SharedStack* referencing idp's security group by ID, i.e.
        # SharedStack -> XrayIdpStack, on top of the XrayIdpStack ->
        # SharedStack this stack already needs. An imported reference, like
        # the mutable SG import used for the frontend->idp rule in
        # XrayFrontendStack, keeps any new rule anchored in this stack
        # instead. See docs/multi-stack.md.
        #
        # allow_all_outbound=False matters here and isn't just documentation:
        # it defaults to True on import, which tells CDK's automatic
        # ALB<->target SG-pairing "this SG already allows all outbound,
        # skip adding an explicit egress rule" - but the real ALB security
        # group was actually created *without* blanket allow-all-outbound
        # (confirmed by inspecting its live egress rules: just CDK's
        # explicit-deny ICMP placeholder, no real 0.0.0.0/0 rule). Passing
        # True here caused CDK to skip the egress rule the ALB actually
        # needs to reach idp on port 3000, so health checks timed out
        # (Target.Timeout) and ECS endlessly replaced tasks - caught by
        # inspecting the live target health and both sides' actual security
        # group rules after a real deploy hung.
        alb_security_group = ec2.SecurityGroup.from_security_group_id(
            self,
            "AlbSecurityGroup",
            shared_stack.alb_security_group.security_group_id,
            allow_all_outbound=False,
        )

        # A cross-stack *reference* to SharedStack's listener, used only to
        # attach an independently-constructed TargetGroup via a priority
        # rule - the listener itself is never mutated. add_targets() looks
        # like the natural one-call API here, but CDK explicitly rejects it
        # on an imported listener at synth time ("Can only call addTargets()
        # when using a constructed ApplicationListener"): the convenience
        # method's target-group bookkeeping needs the real listener object,
        # not a bare reference. add_target_groups() with an explicitly
        # constructed TargetGroup is the documented way around that. See
        # docs/multi-stack.md.
        listener = elbv2.ApplicationListener.from_application_listener_attributes(
            self,
            "SharedListener",
            listener_arn=shared_stack.listener.listener_arn,
            security_group=alb_security_group,
        )

        target_group = elbv2.ApplicationTargetGroup(
            self,
            "IdpTargetGroup",
            vpc=shared_stack.vpc,
            port=80,
            targets=[service],
            health_check=elbv2.HealthCheck(path="/idp/health", healthy_http_codes="200"),
        )

        listener.add_target_groups(
            "IdpTargetGroupAttachment",
            target_groups=[target_group],
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/idp", "/idp/*"])],
        )
