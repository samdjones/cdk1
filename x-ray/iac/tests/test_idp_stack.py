from conftest import IDP, SHARED


def test_idp_paths_are_routed_from_the_shared_listener(elbv2, resources_of_type):
    (alb_arn,) = resources_of_type(SHARED, "AWS::ElasticLoadBalancingV2::LoadBalancer")
    (listener,) = elbv2.describe_listeners(LoadBalancerArn=alb_arn)["Listeners"]
    rules = elbv2.describe_rules(ListenerArn=listener["ListenerArn"])["Rules"]
    idp_rules = [
        r
        for r in rules
        if r["Priority"] != "default"
        and any(
            "/idp" in c.get("PathPatternConfig", {}).get("Values", [])
            for c in r["Conditions"]
        )
    ]
    assert len(idp_rules) == 1
    values = idp_rules[0]["Conditions"][0]["PathPatternConfig"]["Values"]
    assert sorted(values) == ["/idp", "/idp/*"]
    (action,) = idp_rules[0]["Actions"]
    assert action["Type"] == "forward"


def test_idp_service_runs_on_fargate_in_its_own_cluster(ecs, resources_of_type):
    (cluster,) = resources_of_type(IDP, "AWS::ECS::Cluster")
    (service_arn,) = ecs.list_services(cluster=cluster)["serviceArns"]
    (service,) = ecs.describe_services(cluster=cluster, services=[service_arn])[
        "services"
    ]
    assert service["launchType"] == "FARGATE"
    assert service["desiredCount"] == 1


def test_idp_is_registered_in_cloudmap_as_idp(servicediscovery, resources_of_type):
    (namespace_id,) = resources_of_type(
        SHARED, "AWS::ServiceDiscovery::PrivateDnsNamespace"
    )
    services = servicediscovery.list_services(
        Filters=[{"Name": "NAMESPACE_ID", "Values": [namespace_id], "Condition": "EQ"}]
    )["Services"]
    assert "idp" in [s["Name"] for s in services]
