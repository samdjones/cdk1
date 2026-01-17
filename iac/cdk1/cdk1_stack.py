from aws_cdk import (
    Stack,
    aws_ec2 as ec2,
    aws_ecs as ecs,
    aws_ecs_patterns as ecs_patterns,
    aws_lambda as lambda_,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    CfnOutput,
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

        # Configure health check to use /health endpoint
        fargate_service.target_group.configure_health_check(path="/health")

        # Grant ECS task permission to invoke Lambda
        multiply_lambda.grant_invoke(fargate_service.task_definition.task_role)

        # CloudFront distribution with ALB as origin
        distribution = cloudfront.Distribution(
            self,
            "Distribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    fargate_service.load_balancer,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,  # Disable caching for API
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
            ),
            comment="CDK1 Application Distribution",
        )

        # Output CloudFront URL
        CfnOutput(
            self,
            "CloudFrontURL",
            value=f"https://{distribution.distribution_domain_name}",
            description="CloudFront HTTPS URL (use this endpoint)",
        )

        # Output ALB URL for reference
        CfnOutput(
            self,
            "LoadBalancerURL",
            value=f"http://{fargate_service.load_balancer.load_balancer_dns_name}",
            description="ALB HTTP URL (for debugging only)",
        )
