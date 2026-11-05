# CDK demos

Two disposable AWS CDK demos (`x-ray/`, `alb/`) deployed to real AWS, plus a way to rehearse those deploys locally first.

## Language

**Deploy**:
Creating or updating a stack in real AWS.
_Avoid_: Release, publish

**Emulator test**:
A run, local or in CI, that deploys the synthesized stacks into Floci, instead of AWS, and asserts on the resources created. It rehearses a deploy but never touches real AWS.
_Avoid_: Local deploy, smoke test

**E2E test**:
A local-only variant of the emulator test where Floci runs ECS for real: the actual app images run as containers behind the emulated ALB and the test sends HTTP requests through it. Slower, and never run in CI.
_Avoid_: Integration test

**Floci**:
The local AWS emulator that stands in for AWS during an emulator test.
_Avoid_: Floki, LocalStack
