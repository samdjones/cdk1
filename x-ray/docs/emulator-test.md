# Emulator test

Rehearse a deploy locally, or in CI, before touching real AWS. An **emulator
test** starts [Floci](https://floci.io) (a local AWS emulator) in a container,
`cdk bootstrap`s and `cdk deploy`s the stacks into it, then runs pytest/boto3
assertions against what was created. It runs automatically in CI - the
`Emulator test` GitHub workflow triggers on every push and PR (and via
`workflow_dispatch`) - and can be run locally. Only deploying to real AWS is
manual.

```bash
x-ray/ci/emulator_test.sh   # XraySharedStack, XrayIdpStack, XrayFrontendStack
alb/ci/emulator_test.sh     # AlbPocStack
```

Needs `podman` (default) or set `CONTAINER_CLI=docker`; `python3`, `node`/`npm`,
`curl`. The Floci image is pinned in each script (`FLOCI_IMAGE`, currently
`docker.io/floci/floci:2.4.0`) - bump it deliberately. Each run starts a fresh
in-memory Floci and removes it on exit, even on failure. The assertions live in
`<stack>/iac/tests/` and refuse to run unless `AWS_ENDPOINT_URL` points at
localhost.

## What it checks (and doesn't)

Deploy-and-assert only: templates create successfully, cross-stack references
resolve, and key resources exist (listener rules, services, Cloud Map entry,
Lambdas, bucket). ECS runs in Floci's mock mode, so **no containers run and no
traffic is routed** - this does not test application behaviour.

## `-c emulator=true`

The scripts deploy with CDK context `emulator=true`, which `emulator.py` (in
each `iac/` package) reads. Real deploys never set it. It changes:

| Skipped / swapped | Why |
|---|---|
| `ContainerImage.from_asset(...)` -> placeholder registry image | Floci's ECR rejects image pushes without a Docker daemon (and builds are slow); `ci.yml` already builds the images |
| `appsignals.CfnDiscovery` (frontend stack) | `AWS::ApplicationSignals::Discovery` unsupported by Floci |
| ADOT Lambda layer | AWS-owned layer in another account, unreachable from Floci |
| S3 `auto_delete_objects` (frontend stack) | Custom-resource Lambda needs Docker |

Floci is run with `FLOCI_SERVICES_CLOUDFORMATION_ALLOW_STUB_UNSUPPORTED_RESOURCE_TYPES=false`
so any *other* unsupported resource type fails the deploy instead of passing
silently. Add to the table above (and to `emulator.py` usage) only with a reason.
