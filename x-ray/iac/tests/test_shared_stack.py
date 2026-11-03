from conftest import SHARED


def test_public_alb_listener_defaults_to_404(elbv2, resources_of_type):
    (alb_arn,) = resources_of_type(SHARED, "AWS::ElasticLoadBalancingV2::LoadBalancer")
    lb = elbv2.describe_load_balancers(LoadBalancerArns=[alb_arn])["LoadBalancers"][0]
    assert lb["Scheme"] == "internet-facing"

    (listener,) = elbv2.describe_listeners(LoadBalancerArn=alb_arn)["Listeners"]
    assert listener["Port"] == 80
    (action,) = listener["DefaultActions"]
    assert action["Type"] == "fixed-response"
    assert action["FixedResponseConfig"]["StatusCode"] == "404"


def test_cloudmap_private_namespace_xray_local(servicediscovery, resources_of_type):
    (namespace_id,) = resources_of_type(
        SHARED, "AWS::ServiceDiscovery::PrivateDnsNamespace"
    )
    namespace = servicediscovery.get_namespace(Id=namespace_id)["Namespace"]
    assert namespace["Name"] == "xray.local"
    assert namespace["Type"] == "DNS_PRIVATE"
