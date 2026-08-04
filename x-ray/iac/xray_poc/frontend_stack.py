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
)
from constructs import Construct

from xray_poc.shared_stack import XraySharedStack
from xray_poc.idp_stack import XrayIdpStack


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
        adot_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            "AdotLayer",
            f"arn:aws:lambda:{Stack.of(self).region}:901920570463:layer:aws-otel-nodejs-amd64-ver-1-18-1:4",
        )

        # xray-dog-fetcher uses a self-owned copy of the same layer instead
        # of AWS's shared cross-account ARN above - see
        # lambda/xray-dog-fetcher/download-otel-layer.sh and
        # docs/xray-collector-setup.md for why. otel-layer.zip is a vendored,
        # checked-in artifact (prod's own build/deploy can't call any AWS API
        # to fetch it); Code.from_asset uploads a .zip file as-is, no local
        # unzip/rezip needed.
        adot_layer_dogfetcher = lambda_.LayerVersion(
            self,
            "AdotLayerDogFetcher",
            code=lambda_.Code.from_asset("lambda/xray-dog-fetcher/otel-layer.zip"),
            compatible_runtimes=[lambda_.Runtime.NODEJS_22_X],
            description="Vendored AWS Distro for OpenTelemetry Node.js Lambda layer (aws-otel-nodejs-amd64-ver-1-18-1:4), checked in instead of referenced via AWS's shared cross-account layer ARN.",
        )

        common_otel_env = {
            "AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-handler",
            "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_PROPAGATORS": "xray",
            "OTEL_AWS_APPLICATION_SIGNALS_ENABLED": "true",
        }

        # ── S3 Bucket ──────────────────────────────────────────────────────
        dog_bucket = s3.Bucket(
            self,
            "DogBucket",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
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
            layers=[adot_layer],
            timeout=Duration.seconds(60),
            memory_size=256,
        )

        dog_bucket.grant_write(xray_s3_writer_fn)

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
            layers=[adot_layer_dogfetcher],
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        xray_s3_writer_fn.grant_invoke(xray_dog_fetcher_fn)

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
            image=ecs.ContainerImage.from_asset("app-xray"),
            environment={
                "DOG_FETCHER_LAMBDA_NAME": xray_dog_fetcher_fn.function_name,
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
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
        otel_container.add_port_mappings(ecs.PortMapping(container_port=4317))
        otel_container.add_port_mappings(ecs.PortMapping(container_port=4318))

        # ── Envoy sidecar (pass-through reverse proxy in front of the app) ──
        envoy_container = task_definition.add_container(
            "EnvoyProxy",
            image=ecs.ContainerImage.from_asset("envoy"),
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
            layers=[adot_layer],
            timeout=Duration.seconds(30),
            memory_size=256,
        )

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
