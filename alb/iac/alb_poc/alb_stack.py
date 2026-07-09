from aws_cdk import (
    Stack,
    CfnOutput,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_elasticloadbalancingv2 as elbv2,
)
from constructs import Construct


class AlbPocStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── VPC ────────────────────────────────────────────────────────────
        vpc = ec2.Vpc(
            self,
            "AlbVpc",
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
            "AlbCluster",
            vpc=vpc,
            container_insights=True,
        )

        # ── Shared ALB + listener ────────────────────────────────────────
        alb = elbv2.ApplicationLoadBalancer(
            self,
            "Alb",
            vpc=vpc,
            internet_facing=True,
        )
        listener = alb.add_listener("Listener", port=80, open=True)

        def add_backend(name: str) -> ecs.FargateService:
            task_definition = ecs.FargateTaskDefinition(
                self,
                f"{name.capitalize()}TaskDef",
                cpu=256,
                memory_limit_mib=512,
            )
            container = task_definition.add_container(
                f"{name.capitalize()}Container",
                image=ecs.ContainerImage.from_asset(f"app/{name}"),
                environment={"SERVICE_NAME": name},
                logging=ecs.LogDrivers.aws_logs(stream_prefix=f"alb-{name}"),
                essential=True,
            )
            container.add_port_mappings(ecs.PortMapping(container_port=8000))

            return ecs.FargateService(
                self,
                f"{name.capitalize()}Service",
                cluster=cluster,
                task_definition=task_definition,
                desired_count=1,
            )

        main_service = add_backend("main")
        auth_service = add_backend("auth")
        default_service = add_backend("default")

        # ── Path-based routing rules ─────────────────────────────────────
        listener.add_targets(
            "MainTargetGroup",
            port=80,
            targets=[main_service],
            priority=10,
            conditions=[elbv2.ListenerCondition.path_patterns(["/main/*"])],
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )

        listener.add_targets(
            "AuthTargetGroup",
            port=80,
            targets=[auth_service],
            priority=20,
            conditions=[elbv2.ListenerCondition.path_patterns(["/auth/*"])],
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )

        # No priority/conditions ⇒ becomes the listener's default action (catch-all "*")
        listener.add_targets(
            "DefaultTargetGroup",
            port=80,
            targets=[default_service],
            health_check=elbv2.HealthCheck(path="/health", healthy_http_codes="200"),
        )

        # ── CloudFormation Outputs ─────────────────────────────────────────
        CfnOutput(
            self,
            "AlbDnsName",
            value=alb.load_balancer_dns_name,
            description="ALB DNS name - try /main/, /auth/, or any other path",
        )
