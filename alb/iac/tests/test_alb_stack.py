def test_alb_is_internal(elbv2, alb_arn):
    lb = elbv2.describe_load_balancers(LoadBalancerArns=[alb_arn])["LoadBalancers"][0]
    assert lb["Scheme"] == "internal"


def test_listener_routes_paths_and_defaults_to_catch_all(elbv2, alb_arn):
    (listener,) = elbv2.describe_listeners(LoadBalancerArn=alb_arn)["Listeners"]
    assert listener["Port"] == 80

    rules = elbv2.describe_rules(ListenerArn=listener["ListenerArn"])["Rules"]
    by_priority = {r["Priority"]: r for r in rules if r["Priority"] != "default"}
    paths = {
        priority: rule["Conditions"][0]["PathPatternConfig"]["Values"]
        for priority, rule in by_priority.items()
    }
    assert paths == {"10": ["/main/*"], "20": ["/auth/*"]}

    # /main/*, /auth/* and the catch-all default each forward to their own
    # target group.
    def target_groups(actions):
        return {a["TargetGroupArn"] for a in actions if a["Type"] == "forward"}

    main = target_groups(by_priority["10"]["Actions"])
    auth = target_groups(by_priority["20"]["Actions"])
    default = target_groups(listener["DefaultActions"])
    assert len(main) == len(auth) == len(default) == 1
    assert len(main | auth | default) == 3


def test_three_fargate_backend_services_in_one_cluster(ecs, resources_of_type):
    (cluster,) = resources_of_type("AWS::ECS::Cluster")
    service_arns = ecs.list_services(cluster=cluster)["serviceArns"]
    services = ecs.describe_services(cluster=cluster, services=service_arns)["services"]
    assert len(services) == 3
    assert all(s["launchType"] == "FARGATE" for s in services)
    assert all(s["desiredCount"] == 1 for s in services)


def test_bastion_instance_exists_without_inbound_rules(ec2, resources_of_type):
    (instance_id,) = resources_of_type("AWS::EC2::Instance")
    (reservation,) = ec2.describe_instances(InstanceIds=[instance_id])["Reservations"]
    (instance,) = reservation["Instances"]
    group_ids = [g["GroupId"] for g in instance["SecurityGroups"]]
    groups = ec2.describe_security_groups(GroupIds=group_ids)["SecurityGroups"]
    assert all(g["IpPermissions"] == [] for g in groups)
