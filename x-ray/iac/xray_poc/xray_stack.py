from aws_cdk import (
    Stack,
    RemovalPolicy,
    CfnOutput,
    aws_lambda as lambda_,
    aws_ecs as ecs,
    aws_ec2 as ec2,
    aws_s3 as s3,
    aws_iam as iam,
    aws_ecr_assets as ecr_assets,
    aws_elasticloadbalancingv2 as elbv2,
    aws_servicediscovery as servicediscovery,
    Duration,
)
from constructs import Construct
import os


class XrayPocStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── ADOT Lambda layer ──────────────────────────────────────────────
        adot_layer = lambda_.LayerVersion.from_layer_version_arn(
            self,
            "AdotLayer",
            f"arn:aws:lambda:{Stack.of(self).region}:901920570463:layer:aws-otel-nodejs-amd64-ver-1-18-1:4",
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
            layers=[adot_layer],
            timeout=Duration.seconds(30),
            memory_size=256,
        )

        xray_s3_writer_fn.grant_invoke(xray_dog_fetcher_fn)

        # ── VPC ────────────────────────────────────────────────────────────
        vpc = ec2.Vpc(
            self,
            "XrayVpc",
            max_azs=2,
            nat_gateways=1,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="Public",
                    subnet_type=ec2.SubnetType.PUBLIC,
                    cidr_mask=24,
                ),
                ec2.SubnetConfiguration(
                    name="Private",
                    subnet_type=ec2.SubnetType.PRIVATE_WITH_EGRESS,
                    cidr_mask=24,
                ),
            ],
        )

        # ── ECS Cluster ────────────────────────────────────────────────────
        cluster = ecs.Cluster(
            self,
            "XrayCluster",
            vpc=vpc,
            container_insights=True,
        )

        # ── ECS Task Definition ────────────────────────────────────────────
        task_definition = ecs.FargateTaskDefinition(
            self,
            "XrayTaskDef",
            cpu=512,
            memory_limit_mib=1024,
        )

        # Grant X-Ray write access to the task role
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

        # Allow the ECS task to invoke the dog fetcher Lambda
        xray_dog_fetcher_fn.grant_invoke(task_definition.task_role)

        # ── App container ──────────────────────────────────────────────────
        app_image = ecs.ContainerImage.from_asset(
            "app-xray",
        )

        app_container = task_definition.add_container(
            "AppContainer",
            image=app_image,
            environment={
                "DOG_FETCHER_LAMBDA_NAME": xray_dog_fetcher_fn.function_name,
                "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
                "OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
                "OTEL_SERVICE_NAME": "xray-frontend",
                "OTEL_PROPAGATORS": "xray",
                "AWS_XRAY_DAEMON_ADDRESS": "localhost:2000",
                "OTEL_AWS_APPLICATION_SIGNALS_ENABLED": "true",
                "NODE_OPTIONS": "--require /app/otel-bootstrap.js",
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
        # Expose OTLP gRPC and HTTP ports (reachable via localhost in Fargate awsvpc mode)
        otel_container.add_port_mappings(ecs.PortMapping(container_port=4317))
        otel_container.add_port_mappings(ecs.PortMapping(container_port=4318))

        # ── Envoy sidecar (pass-through reverse proxy in front of the app) ──
        envoy_image = ecs.ContainerImage.from_asset("envoy")

        envoy_container = task_definition.add_container(
            "EnvoyProxy",
            image=envoy_image,
            logging=ecs.LogDrivers.aws_logs(stream_prefix="xray-envoy"),
            essential=True,
        )
        envoy_container.add_port_mappings(ecs.PortMapping(container_port=8080))

        # Envoy now fronts the task, so it - not the app container - is the
        # ALB's target.
        task_definition.default_container = envoy_container

        # ── ECS Cluster (idp) ─────────────────────────────────────────────────
        idp_cluster = ecs.Cluster(
            self,
            "XrayIdpCluster",
            vpc=vpc,
            container_insights=True,
        )

        # ── CloudMap private DNS namespace ───────────────────────────────────
        # Lets the frontend resolve the idp service by name (idp.xray.local)
        # over a private call, without going through the public ALB.
        cloud_map_namespace = servicediscovery.PrivateDnsNamespace(
            self,
            "XrayNamespace",
            name="xray.local",
            vpc=vpc,
        )

        # ── ECS Task Definition (idp) ────────────────────────────────────────
        idp_task_definition = ecs.FargateTaskDefinition(
            self,
            "XrayIdpTaskDef",
            cpu=512,
            memory_limit_mib=1024,
        )

        idp_task_definition.task_role.add_to_policy(
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

        idp_app_container = idp_task_definition.add_container(
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
        idp_app_container.add_port_mappings(ecs.PortMapping(container_port=3000))

        # OTEL Collector sidecar - same role as the frontend's, no Envoy here.
        idp_otel_container = idp_task_definition.add_container(
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
        idp_otel_container.add_port_mappings(ecs.PortMapping(container_port=4317))
        idp_otel_container.add_port_mappings(ecs.PortMapping(container_port=4318))

        idp_cloud_map_name = "idp"
        idp_container_port = 3000

        idp_service = ecs.FargateService(
            self,
            "XrayIdpService",
            cluster=idp_cluster,
            task_definition=idp_task_definition,
            desired_count=1,
            cloud_map_options=ecs.CloudMapOptions(
                name=idp_cloud_map_name,
                cloud_map_namespace=cloud_map_namespace,
                dns_record_type=servicediscovery.DnsRecordType.A,
                container_port=idp_container_port,
            ),
            # The "60s if a load balancer is in use" default only applies
            # when load balancers are passed at construction time; attaching
            # via listener.add_targets() afterward doesn't get it for free.
            health_check_grace_period=Duration.seconds(60),
        )

        # The frontend's side-call to idp goes straight to idp's task ENI via
        # CloudMap, bypassing the ALB, so it needs its own SG rule - the ALB
        # target group wiring below only opens ingress from the ALB.
        idp_url = f"http://{idp_cloud_map_name}.{cloud_map_namespace.namespace_name}:{idp_container_port}"
        app_container.add_environment("IDP_URL", idp_url)

        # ── Frontend ECS Service ─────────────────────────────────────────────
        frontend_service = ecs.FargateService(
            self,
            "XrayFargateService",
            cluster=cluster,
            task_definition=task_definition,
            desired_count=1,
            health_check_grace_period=Duration.seconds(60),
        )

        idp_service.connections.allow_from(
            frontend_service,
            ec2.Port.tcp(idp_container_port),
            "Allow the frontend to call idp /idp/health via CloudMap",
        )

        # idp must be up and stable before the frontend deploys, since the
        # frontend calls idp's health endpoint before serving traffic. Scoped
        # to just the two ECS::Service resources (not construct-level
        # add_dependency) - a construct-level dependency fans out to every
        # resource in both subtrees, including the SG ingress rule above
        # that legitimately references frontend's own SG, which creates a
        # real cycle.
        frontend_service.node.default_child.add_dependency(idp_service.node.default_child)

        # ── Shared public ALB with path-based routing ────────────────────────
        alb = elbv2.ApplicationLoadBalancer(
            self,
            "SharedAlb",
            vpc=vpc,
            internet_facing=True,
        )
        listener = alb.add_listener("Listener", port=80, open=True)

        listener.add_targets(
            "IdpTargetGroup",
            port=80,
            targets=[idp_service],
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/idp", "/idp/*"])],
            health_check=elbv2.HealthCheck(path="/idp/health", healthy_http_codes="200"),
        )

        # No priority/conditions ⇒ becomes the listener's default action (catch-all "*")
        listener.add_targets(
            "FrontendTargetGroup",
            port=80,
            targets=[frontend_service],
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )

        # ── Lambda Invoker ─────────────────────────────────────────────────
        alb_url = f"http://{alb.load_balancer_dns_name}/fetch-dog"

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
            "AlbDnsName",
            value=alb.load_balancer_dns_name,
            description=(
                "Shared ALB DNS name - default path routes to xray-frontend, "
                "/idp and /idp/* route to xray-idp"
            ),
        )

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

