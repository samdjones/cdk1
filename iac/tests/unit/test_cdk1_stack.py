import aws_cdk as core
import aws_cdk.assertions as assertions

from cdk1.cdk1_stack import Cdk1Stack

# example tests. To run these tests, uncomment this file along with the example
# resource in cdk1/cdk1_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = Cdk1Stack(app, "cdk1")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
