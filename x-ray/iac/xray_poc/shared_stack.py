from aws_cdk import (
    Stack,
    CfnOutput,
    aws_ec2 as ec2,
    aws_elasticloadbalancingv2 as elbv2,
    aws_servicediscovery as servicediscovery,
)
from constructs import Construct


class XraySharedStack(Stack):
    """
    Infrastructure shared by both service stacks: the VPC, the public ALB
    (with its listener), and the CloudMap private DNS namespace. Neither
    XrayIdpStack nor XrayFrontendStack owns any of this - they each import
    it and attach their own resources to it.

    The listener's default action is a static fixed response, set once
    here and never touched again. Each service stack registers itself via
    an explicit priority-based path-pattern rule instead of relying on
    "no conditions = default action" - CloudFormation only allows the
    stack that *owns* the Listener resource to mutate its DefaultActions
    property, so a true default action pointing at a service in another
    stack isn't achievable without folding the listener's default action
    edits back into this stack every time a service stack changes. Explicit
    rules on both sides route around that limitation entirely: registering
    a target group behind a priority rule creates an independent
    ListenerRule resource that only needs the listener's ARN, which is
    fine to import cross-stack. See docs/multi-stack.md.
    """

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ── VPC ────────────────────────────────────────────────────────────
        self.vpc = ec2.Vpc(
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

        # ── CloudMap private DNS namespace ───────────────────────────────────
        self.cloud_map_namespace = servicediscovery.PrivateDnsNamespace(
            self,
            "XrayNamespace",
            name="xray.local",
            vpc=self.vpc,
        )

        # ── Shared public ALB with path-based routing ────────────────────────
        self.alb = elbv2.ApplicationLoadBalancer(
            self,
            "SharedAlb",
            vpc=self.vpc,
            internet_facing=True,
        )
        self.alb_security_group = self.alb.connections.security_groups[0]

        self.listener = self.alb.add_listener(
            "Listener",
            port=80,
            open=True,
            default_action=elbv2.ListenerAction.fixed_response(
                404,
                content_type="text/plain",
                message_body="Not Found",
            ),
        )

        # ── CloudFormation Outputs ─────────────────────────────────────────
        CfnOutput(
            self,
            "AlbDnsName",
            value=self.alb.load_balancer_dns_name,
            description=(
                "Shared ALB DNS name - default path routes to xray-frontend, "
                "/idp and /idp/* route to xray-idp"
            ),
        )
