from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_lambda as lambda_,
)
from constructs import Construct


class Cdk1Stack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # VPC with public/private subnets across 2 AZs
        vpc = ec2.Vpc(self, "Vpc", max_azs=2)

        # ECS Cluster
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        # Lambda function for multiplication
        multiply_lambda = lambda_.Function(
            self,
            "MultiplyFunction",
            runtime=lambda_.Runtime.NODEJS_22_X,
            handler="handler.handler",
            code=lambda_.Code.from_asset("../lambda/multiply/dist"),
        )

        # Fargate service with ALB (builds image from app/Dockerfile)
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self,
            "Service",
            cluster=cluster,
            cpu=256,
            memory_limit_mib=512,
            desired_count=1,
            task_image_options=ecs_patterns.ApplicationLoadBalancedTaskImageOptions(
                image=ecs.ContainerImage.from_asset("../app"),
                container_port=8000,
                environment={
                    "MULTIPLY_LAMBDA_NAME": multiply_lambda.function_name,
                },
            ),
            public_load_balancer=True,
        )

        # Grant ECS task permission to invoke Lambda
        multiply_lambda.grant_invoke(fargate_service.task_definition.task_role)
