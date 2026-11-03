from conftest import FRONTEND, SHARED


def test_frontend_stack_resolved_its_cross_stack_imports(cfn):
    # The stack deploying at all means every Fn::ImportValue resolved against
    # the Shared and Idp exports; assert the exports exist and it completed.
    (stack,) = cfn.describe_stacks(StackName=FRONTEND)["Stacks"]
    assert stack["StackStatus"] == "CREATE_COMPLETE"
    exports = {e["Name"] for e in cfn.list_exports()["Exports"]}
    assert any(name.startswith(SHARED) for name in exports)


def test_three_lambdas_exist(lambda_, resources_of_type):
    names = resources_of_type(FRONTEND, "AWS::Lambda::Function")
    # The S3 auto-delete custom-resource function is skipped in emulator runs,
    # leaving exactly the three application functions.
    assert len(names) == 3
    for name in names:
        assert lambda_.get_function(FunctionName=name)["Configuration"]["Runtime"]


def test_one_dog_bucket_exists(s3, resources_of_type):
    (bucket,) = resources_of_type(FRONTEND, "AWS::S3::Bucket")
    names = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    assert bucket in names


def test_frontend_service_runs_on_fargate(ecs, resources_of_type):
    (cluster,) = resources_of_type(FRONTEND, "AWS::ECS::Cluster")
    (service_arn,) = ecs.list_services(cluster=cluster)["serviceArns"]
    (service,) = ecs.describe_services(cluster=cluster, services=[service_arn])[
        "services"
    ]
    assert service["launchType"] == "FARGATE"
    assert service["desiredCount"] == 1
