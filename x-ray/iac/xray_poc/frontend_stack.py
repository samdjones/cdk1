from aws_cdk import (
    Stack,
    Duration,
    RemovalPolicy,
    CfnOutput,
    aws_lambda as lambda_,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_s3 as s3,
    aws_iam as iam,
    aws_elasticloadbalancingv2 as elbv2,
    aws_applicationsignals as appsignals,
)
from constructs import Construct

from xray_poc.app_signals import APP_SIGNALS_OTEL_ENV, add_cloudwatch_agent_sidecar
from xray_poc.shared_stack import XraySharedStack
from xray_poc.idp_stack import XrayIdpStack
from xray_poc.emulator import container_image, is_emulator


class XrayFrontendStack(Stack):
    """
    The xray-frontend backend: its own ECS cluster, task (app + OTel
    collector + Envoy), and service; the three Lambdas it talks to
    (invoker, dog-fetcher, s3-writer); and the S3 bucket. Registered on
    the shared ALB via a catch-all priority rule (not the listener's
    default action - see XraySharedStack's docstring).

    Depends on XraySharedStack (VPC, ALB listener, CloudMap namespace) and
    on XrayIdpStack (idp's security group, for the ingress rule that lets
    this service's CloudMap side-call reach it - see docs/multi-stack.md).
    That security-group import already forces CDK to deploy XrayIdpStack
    first; add_dependency() below makes that requirement explicit instead
    of incidental, matching how the in-task Envoy->app container
    dependency was made explicit rather than relying on the ALB health
    check to paper over missing ordering.
    """

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        shared_stack: XraySharedStack,
        idp_stack: XrayIdpStack,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.add_dependency(idp_stack)

        # ── ADOT Lambda layer ──────────────────────────────────────────────
        # New-style AWSOpenTelemetryDistroJs layer (the "recommended" approach
        # per https://aws-otel.github.io/docs/getting-started/lambda), not the
        # legacy aws-otel-nodejs-* layer. See docs/xray-collector-setup.md for
        # the exec wrapper / instrumentation-defaults differences this brings.
        adot_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            "AdotLayer",
            f"arn:aws:lambda:{Stack.of(self).region}:615299751070:layer:AWSOpenTelemetryDistroJs:15",
        )

        # Emulator-test skip list: the ADOT layer lives in an AWS-owned
        # account Floci can't reach (docs/emulator-test.md).
        adot_layers = [] if is_emulator(self) else [adot_layer]

        common_otel_env = {
            "AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-instrument",
            # No OTEL_EXPORTER_OTLP_PROTOCOL override (was "grpc" under the
            # old layer) - this layer has no embedded local collector to
            # gRPC to. With Application Signals off, it auto-points OTLP
            # traces straight at https://xray.<region>.amazonaws.com/v1/traces
            # (confirmed by reading the unpacked layer's wrapper.js), an
            # HTTPS/REST-style endpoint - forcing gRPC here would break
            # export. Its own http/protobuf default is correct as-is.
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_PROPAGATORS": "xray",
            # New layer only auto-instruments aws-sdk/http by default (for
            # faster cold starts) - "none" restores full coverage (undici
            # included), matching the old layer's always-everything-on
            # default that xray-dog-fetcher's fetch() call to the Dog CEO
            # API relies on for its own span.
            "OTEL_NODE_DISABLED_INSTRUMENTATIONS": "none",
            # Enabled - see docs/xray-collector-setup.md. Also requires the
            # CloudWatchLambdaApplicationSignalsExecutionRolePolicy managed
            # policy on each function's role (below) and the one-time
            # CfnDiscovery resource per account/region (also below).
            "OTEL_AWS_APPLICATION_SIGNALS_ENABLED": "true",
        }

        # One-time, account/region-scoped resource that opts the account in
        # to Application Signals service discovery. Only needs to exist
        # once per account/region - placed here (not in XraySharedStack)
        # because this is the stack that actually enables Application
        # Signals on anything.
        #
        # Emulator-test skip list: Floci doesn't support
        # AWS::ApplicationSignals::Discovery (see docs/emulator-test.md).
        if not is_emulator(self):
            appsignals.CfnDiscovery(self, "ApplicationSignalsDiscovery")

        application_signals_policy = iam.ManagedPolicy.from_aws_managed_policy_name(
            "CloudWatchLambdaApplicationSignalsExecutionRolePolicy"
        )

        # ── S3 Bucket ──────────────────────────────────────────────────────
        dog_bucket = s3.Bucket(
            self,
            "DogBucket",
            removal_policy=RemovalPolicy.DESTROY,
            # Emulator-test skip list: this adds a custom-resource Lambda that
            # runs in Docker, which Floci can't do here (docs/emulator-test.md).
            auto_delete_objects=not is_emulator(self),
            versioned=False,
        )

        # ── Lambda S3 Writer ───────────────────────────────────────────────
        xray_s3_writer_fn = lambda_.Function(
            self,
            "XrayS3WriterFn",
            function_name="xray-s3-writer",
            runtime=lambda_.Runtime.NODEJS_22_X,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambda/xray-s3-writer/dist"),
            environment={
                **common_otel_env,
                "DOG_BUCKET_NAME": dog_bucket.bucket_name,
            },
            tracing=lambda_.Tracing.ACTIVE,
            layers=adot_layers,
            timeout=Duration.seconds(60),
            memory_size=256,
        )

        dog_bucket.grant_write(xray_s3_writer_fn)
        xray_s3_writer_fn.role.add_managed_policy(application_signals_policy)

        # ── Lambda Dog Fetcher ─────────────────────────────────────────────
        xray_dog_fetcher_fn = lambda_.Function(
            self,
            "XrayDogFetcherFn",
            function_name="xray-dog-fetcher",
            runtime=lambda_.Runtime.NODEJS_22_X,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambda/xray-dog-fetcher/dist"),
            environment={
                **common_otel_env,
                "S3_WRITER_FUNCTION_NAME": xray_s3_writer_fn.function_name,
            },
            tracing=lambda_.Tracing.ACTIVE,
            layers=adot_layers,
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        xray_s3_writer_fn.grant_invoke(xray_dog_fetcher_fn)
        xray_dog_fetcher_fn.role.add_managed_policy(application_signals_policy)

        # ── ECS Cluster ────────────────────────────────────────────────────
        cluster = ecs.Cluster(
            self,
            "XrayCluster",
            vpc=shared_stack.vpc,
            container_insights=True,
        )

        # ── ECS Task Definition ────────────────────────────────────────────
        task_definition = ecs.FargateTaskDefinition(
            self,
            "XrayTaskDef",
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

        xray_dog_fetcher_fn.grant_invoke(task_definition.task_role)

        # ── App container ──────────────────────────────────────────────────
        idp_url = f"http://{idp_stack.cloud_map_name}.{shared_stack.cloud_map_namespace.namespace_name}:{idp_stack.container_port}"

        app_container = task_definition.add_container(
            "AppContainer",
            image=container_image(self, "app-xray"),
            environment={
                "DOG_FETCHER_LAMBDA_NAME": xray_dog_fetcher_fn.function_name,
                **APP_SIGNALS_OTEL_ENV,
                "OTEL_SERVICE_NAME": "xray-frontend",
                "OTEL_PROPAGATORS": "xray",
                "AWS_XRAY_DAEMON_ADDRESS": "localhost:2000",
                "OTEL_AWS_APPLICATION_SIGNALS_ENABLED": "true",
                "NODE_OPTIONS": "--require /app/otel-bootstrap.js",
                "IDP_URL": idp_url,
            },
            logging=ecs.LogDrivers.aws_logs(stream_prefix="xray-app"),
            essential=True,
        )
        app_container.add_port_mappings(ecs.PortMapping(container_port=8000))

        # ── OTEL Collector sidecar ─────────────────────────────────────────
        # Only needed for Envoy's native X-Ray tracer, which ships segments over
        # the classic UDP daemon protocol on port 2000 (see docs/envoy.md). The
        # app's own telemetry goes to the CloudWatchAgent sidecar below.
        otel_container = task_definition.add_container(
            "OtelCollector",
            image=ecs.ContainerImage.from_registry(
                "public.ecr.aws/aws-observability/aws-otel-collector:latest"
            ),
            command=["--config=/etc/ecs/ecs-default-config.yaml"],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="xray-otel"),
            essential=False,
            environment={
                "AWS_REGION": Stack.of(self).region,
            },
        )

        # ── CloudWatch Agent sidecar (Application Signals for this task) ───
        add_cloudwatch_agent_sidecar(task_definition, "CloudWatchAgent", "xray-cwagent", app_container)

        # ── Envoy sidecar (pass-through reverse proxy in front of the app) ──
        envoy_container = task_definition.add_container(
            "EnvoyProxy",
            image=container_image(self, "envoy"),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="xray-envoy"),
            essential=True,
        )
        envoy_container.add_port_mappings(ecs.PortMapping(container_port=8080))

        envoy_container.add_container_dependencies(
            ecs.ContainerDependency(
                container=app_container,
                condition=ecs.ContainerDependencyCondition.START,
            )
        )

        # Envoy now fronts the task, so it - not the app container - is the
        # ALB's target.
        task_definition.default_container = envoy_container

        # ── ECS Service ──────────────────────────────────────────────────────
        service = ecs.FargateService(
            self,
            "XrayFargateService",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            health_check_grace_period=Duration.seconds(60),
        )

        # Reach across to XrayIdpStack's security group and add an ingress
        # rule from this service's own SG. Using a local, mutable reference
        # (SecurityGroup.from_security_group_id) rather than the real object
        # keeps the new SecurityGroupIngress resource here in
        # XrayFrontendStack, not in XrayIdpStack - the opposite direction
        # would create a stack cycle, since XrayFrontendStack already has to
        # deploy after XrayIdpStack. See docs/multi-stack.md.
        idp_security_group = ec2.SecurityGroup.from_security_group_id(
            self,
            "IdpSecurityGroup",
            idp_stack.security_group.security_group_id,
        )
        idp_security_group.add_ingress_rule(
            peer=service.connections.security_groups[0],
            connection=ec2.Port.tcp(idp_stack.container_port),
            description="Allow the frontend to call idp /idp/health via CloudMap",
        )

        # ── ALB registration ─────────────────────────────────────────────────
        # Same cross-stack-listener pattern as XrayIdpStack (constructed
        # TargetGroup + add_target_groups(), not add_targets() - see
        # XrayIdpStack's comment for why), but as a catch-all priority rule
        # rather than the listener's default action - see XraySharedStack's
        # docstring for why that specifically can't move to this stack.
        #
        # Also imports the ALB's security group locally rather than reusing
        # shared_stack.alb_security_group directly, same reasoning as
        # XrayIdpStack: this stack already depends on SharedStack, so a
        # resource that referenced it back would cycle.
        #
        # allow_all_outbound=False: the real ALB security group has no
        # blanket allow-all-outbound rule, so the default (True) on this
        # import would make CDK skip the egress rule the ALB actually needs
        # to reach the frontend - see XrayIdpStack's comment, where this
        # exact gap caused ALB health checks to time out against a live
        # deploy.
        alb_security_group = ec2.SecurityGroup.from_security_group_id(
            self,
            "AlbSecurityGroup",
            shared_stack.alb_security_group.security_group_id,
            allow_all_outbound=False,
        )

        listener = elbv2.ApplicationListener.from_application_listener_attributes(
            self,
            "SharedListener",
            listener_arn=shared_stack.listener.listener_arn,
            security_group=alb_security_group,
        )

        target_group = elbv2.ApplicationTargetGroup(
            self,
            "FrontendTargetGroup",
            vpc=shared_stack.vpc,
            port=80,
            targets=[service],
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )

        listener.add_target_groups(
            "FrontendTargetGroupAttachment",
            target_groups=[target_group],
            priority=100,
            conditions=[elbv2.ListenerCondition.path_patterns(["/*"])],
        )

        # ── Lambda Invoker ─────────────────────────────────────────────────
        alb_url = f"http://{shared_stack.alb.load_balancer_dns_name}/fetch-dog"

        xray_invoker_fn = lambda_.Function(
            self,
            "XrayInvokerFn",
            function_name="xray-invoker",
            runtime=lambda_.Runtime.NODEJS_22_X,
            handler="handler.handler",
            code=lambda_.Code.from_asset("lambda/xray-invoker/dist"),
            environment={
                **common_otel_env,
                "FRONTEND_URL": alb_url,
            },
            tracing=lambda_.Tracing.ACTIVE,
            layers=adot_layers,
            timeout=Duration.seconds(30),
            memory_size=256,
        )
        xray_invoker_fn.role.add_managed_policy(application_signals_policy)

        # ── CloudFormation Outputs ─────────────────────────────────────────
        CfnOutput(
            self,
            "InvokerLambdaName",
            value=xray_invoker_fn.function_name,
            description="Lambda Invoker function name - trigger this to start the X-Ray trace",
        )

        CfnOutput(
            self,
            "DogBucketName",
            value=dog_bucket.bucket_name,
            description="S3 bucket where dog images and metadata are stored",
        )

        CfnOutput(
            self,
            "DogFetcherLambdaName",
            value=xray_dog_fetcher_fn.function_name,
            description="Dog Fetcher Lambda function name",
        )
