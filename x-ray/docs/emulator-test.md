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

## E2E test (alb, local only)

`alb/ci/e2e_test.sh` goes further: Floci runs ECS **for real**, so the actual
`alb/app/{main,auth,default}` images run as containers behind Floci's ALB, and
`alb/iac/e2e/` sends HTTP requests through the listener
(`/main/*`, `/auth/*`, default). It is not run in CI (slower; needs a container
API socket). How it differs from the emulator test:

- Images are built locally (`localhost/cdk1-alb-<svc>:e2e`) and used from the
  local store via `FLOCI_SERVICES_ECS_IMAGE_PULL_BEHAVIOR=prefer-cached` - no ECR
  push. `-c e2e=true` (with `-c emulator=true`) makes `emulator.py` use them.
- ECS mock is off; Floci gets the podman/docker API socket and a shared network.
- Floci's ALB data plane binds port 80 as non-root, so the Floci container sets
  `net.ipv4.ip_unprivileged_port_start=0`; port 80 is published on
  `E2E_ALB_PORT` (default 8088).

## E2E test (x-ray, local only)

`x-ray/ci/e2e_test.sh` runs the three x-ray stacks with real ECS and Lambda in
Floci: the real `app-xray` / `app-idp` containers and the three Lambdas run, and
`x-ray/iac/e2e/` sends requests through the ALB (`/idp/health`, `/health`, and
`/fetch-dog` = ALB -> frontend -> dog-fetcher Lambda -> s3-writer Lambda -> S3,
then reads the objects back). Needs internet (dog.ceo). Same mechanics as the
alb E2E test above; run with `KEEP=1` to leave Floci up for
`podman logs -f floci-e2e-xray`. Extra skips under `-c e2e=true`:

| Skipped / swapped | Why |
|---|---|
| Envoy sidecars (ALB targets the app container) | Floci only shares a task's network namespace (Envoy -> app on `127.0.0.1`) with security-group enforcement, which needs rootful Docker; rootless podman fails with "Security-group enforcement requires rootful Docker" |
| Lambda `AWS_LAMBDA_EXEC_WRAPPER` | The wrapper ships in the ADOT layer, which is skipped, so the runtime would exit 127 |
| App containers' AWS SDK pointed at Floci (`e2e_env`) | They must reach Floci, not real AWS |

The OTel collector sidecar isn't functional, so the apps log harmless
`ECONNREFUSED :4317` export errors.

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
