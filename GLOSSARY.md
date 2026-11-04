# CDK demos

Two disposable AWS CDK demos (`x-ray/`, `alb/`) deployed to real AWS, plus a way to rehearse those deploys locally first.

## Language

**Deploy**:
Creating or updating a stack in real AWS.
_Avoid_: Release, publish

**Emulator test**:
A run, local or in CI, that deploys the synthesized stacks into Floci, instead of AWS, and asserts on the resources created. It rehearses a deploy but never touches real AWS.
_Avoid_: Local deploy, integration test, smoke test

**Floci**:
The local AWS emulator that stands in for AWS during an emulator test.
_Avoid_: Floki, LocalStack
