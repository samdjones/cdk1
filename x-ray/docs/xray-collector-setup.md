# X-Ray Collector Setup: ECS and Lambda

This document explains how OpenTelemetry traces are collected and exported to AWS X-Ray in the X-Ray POC stack.

## Overview

Both the ECS Fargate service and the Lambda functions use the **AWS Distro for OpenTelemetry (ADOT)** to collect and export traces. ADOT is AWS's distribution of the OpenTelemetry project — it bundles the OTel SDK, auto-instrumentation agents, and a collector pre-configured to work with AWS services including X-Ray.

The two environments use different ADOT packaging because of their different execution models:

| | Lambda | ECS Fargate |
|---|---|---|
| Collector packaging | None — Lambda Layer talks directly to AWS | Sidecar container |
| Auto-instrumentation | `otel-instrument` exec wrapper | Node.js agent via `NODE_OPTIONS` |
| Collector config | N/A (no local collector) | `ecs-default-config.yaml` (baked into image) |
| Export destination | X-Ray, direct OTLP/HTTP (SigV4-signed) | X-Ray (via OTEL collector sidecar) |

---

## Lambda: ADOT Lambda Layer

### How it works

This uses the **new/recommended** ADOT Lambda approach ([aws-otel.github.io/docs/getting-started/lambda](https://aws-otel.github.io/docs/getting-started/lambda)), not the legacy `aws-otel-nodejs-*` layer + `/opt/otel-handler` setup (still documented at the now-superseded [`lambda-js`](https://aws-otel.github.io/docs/getting-started/lambda/lambda-js) page) this repo used before. The new approach is built around **CloudWatch Application Signals**, but Application Signals is **deliberately not enabled here** — this migrates only the existing X-Ray tracing functionality; see [Application Signals: deliberately not enabled](#application-signals-deliberately-not-enabled) below.

The layer is attached via CDK:

```python
# iac/xray_poc/frontend_stack.py
adot_layer = lambda_.LayerVersion.from_layer_version_arn(
    self,
    "AdotLayer",
    f"arn:aws:lambda:{Stack.of(self).region}:615299751070:layer:AWSOpenTelemetryDistroJs:15",
)
```

The layer ARN account `615299751070` is AWS's own — a different account than the legacy layer's `901920570463`, and a different layer name (`AWSOpenTelemetryDistroJs`, no `amd64`/`arm64` split — confirmed empirically that arch-suffixed variants of this name don't exist; it's architecture-agnostic).

There's no `list-layer-versions` API available for a layer published by a different account — only `get-layer-version`, which reads one specific version number at a time and is allowed cross-account by the layer's own public resource policy. `find-latest-otel-layer-version.sh [region]` (repo root: `x-ray/`) finds the latest published version number, by probing version numbers upward and tolerating gaps. Run it before bumping the version in the ARN above.

Unlike the legacy layer, **there's no embedded collector binary** — confirmed by unpacking the layer zip (2MB vs. the old layer's 18–30MB, and no `extensions/` directory for a Lambda Extension process). Instead, the OTel SDK exports spans directly over OTLP/HTTP straight to AWS, using SigV4-signed requests (confirmed present in the layer's bundled `wrapper.js`) — no local collector process, no `OTEL_EXPORTER_OTLP_ENDPOINT` to configure by hand.

### The exec wrapper: `AWS_LAMBDA_EXEC_WRAPPER`

The key to zero-code-change instrumentation is this environment variable:

```python
"AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-instrument",
```

Note the path: `/opt/otel-instrument`, not the legacy layer's `/opt/otel-handler`. Lambda supports an exec wrapper mechanism: before running your handler, Lambda executes the binary at the path in `AWS_LAMBDA_EXEC_WRAPPER`, which in turn starts your handler. Read straight from the unpacked layer's `otel-instrument` script, it:

1. Adds `--require /opt/wrapper.js` (or `--import /opt/wrapper.mjs` for ESM handlers) to `NODE_OPTIONS`, to load the instrumentation before your code runs
2. Sets defaults for anything not already set in the environment — notably `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf`, `OTEL_PROPAGATORS=baggage,tracecontext,xray`, `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true`, `OTEL_METRICS_EXPORTER=none`, `OTEL_LOGS_EXPORTER=none`, and — critically for cold-start time — `OTEL_NODE_ENABLED_INSTRUMENTATIONS=aws-sdk,aws-lambda,http` (a much narrower default than the legacy layer's "everything on"; see below)
3. Starts your handler process as normal (`exec "$@"`)

This means your handler code requires **no changes** — AWS SDK calls, HTTP requests, and Lambda invocations are automatically traced, once the reduced default instrumentation set is widened back out (next section).

### Restoring full instrumentation coverage: `OTEL_NODE_DISABLED_INSTRUMENTATIONS`

To reduce cold-start time, this layer **only auto-instruments `aws-sdk`, `aws-lambda`, and `http` by default** — a narrower set than the legacy layer's "every instrumentation on unless explicitly disabled" default. That default would silently drop span coverage for `undici`/global `fetch()` calls — which `xray-dog-fetcher` needs for its own span around its call to the Dog CEO API. Setting it to `none` (a literal string, not "empty" — it works because `"none"` isn't a real instrumentation package name, so nothing in the real instrumentation set actually matches it and gets disabled) restores full coverage, matching the old default:

```python
"OTEL_NODE_DISABLED_INSTRUMENTATIONS": "none",
```

This is AWS's own documented mechanism for this — see [Enabling all library instrumentations](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-Application-Signals-Enable-Lambda.html#Configuring-Lambda-AppSignals).

### No `OTEL_EXPORTER_OTLP_PROTOCOL` override

The legacy layer's environment set `OTEL_EXPORTER_OTLP_PROTOCOL=grpc` (gRPC to the embedded local collector). This layer has no local collector to gRPC to, and — confirmed against AWS's own [OTLP Endpoints](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLPEndpoint.html) docs — **the X-Ray OTLP traces endpoint only supports HTTP, not gRPC** at all. So this env var is left unset here, letting the layer's own `http/protobuf` default apply; setting `grpc` would silently break export.

### Application Signals: deliberately not enabled

```python
"OTEL_AWS_APPLICATION_SIGNALS_ENABLED": "false",
```

The layer defaults this to `true` if unset — so it has to be explicitly forced off here to keep this migration scoped to "same X-Ray tracing, new layer" rather than also turning on Application Signals' APM dashboards/SLOs. Confirmed by reading the layer's `wrapper.js`: when this is `"false"` and no explicit `OTEL_EXPORTER_OTLP_ENDPOINT` is set, it auto-configures `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=https://xray.<region>.amazonaws.com/v1/traces` — AWS's native OTLP-to-X-Ray ingestion endpoint — which is exactly the plain-X-Ray behavior this migration is meant to preserve.

Turning Application Signals on later (out of scope for this change) would additionally require attaching the AWS-managed `CloudWatchLambdaApplicationSignalsExecutionRolePolicy` IAM policy to each function's role, and a one-time `aws_applicationsignals.CfnDiscovery` CDK resource per account/region.

### IAM permissions

No IAM changes were needed for this migration. `tracing=lambda_.Tracing.ACTIVE` already grants each function's role `xray:PutTraceSegments` and `xray:PutTelemetryRecords` (plus the sampling-rule actions) via CDK's built-in X-Ray grant — the same permissions [AWS's own docs](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/CloudWatch-OTLP-UsingADOT.html) list as required for OTLP-to-X-Ray export.

### Active tracing

CDK enables X-Ray active tracing on each Lambda:

```python
tracing=lambda_.Tracing.ACTIVE,
```

This tells the Lambda service to create an X-Ray trace segment for every invocation and pass the `_X_AMZN_TRACE_ID` header into the execution environment. The ADOT layer picks this up and uses it as the root segment, so all child spans (SDK calls, HTTP calls) nest under the same trace — see [Manual vs. automatic propagation](#manual-vs-automatic-propagation) below for the one place this still needs help.

### What gets traced automatically

- Outbound HTTP/HTTPS requests (including global `fetch()`, via `undici` — only with `OTEL_NODE_DISABLED_INSTRUMENTATIONS=none` set, see above)
- AWS SDK v3 client calls (Lambda `InvokeCommand`, S3 `PutObjectCommand`)
- The Lambda invocation itself (as the root segment)

### Environment variables summary

```
AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-instrument       # activates the layer's wrapper
OTEL_PROPAGATORS=xray                               # use X-Ray trace context format
OTEL_TRACES_EXPORTER=otlp                           # export via OTLP (redundant with the layer's own default, kept explicit)
OTEL_NODE_DISABLED_INSTRUMENTATIONS=none            # restore full instrumentation coverage (see above)
OTEL_AWS_APPLICATION_SIGNALS_ENABLED=false           # keep plain X-Ray export, no Application Signals (see above)
```

Not set (left to the layer's own defaults, since overriding them would be wrong here): `OTEL_EXPORTER_OTLP_PROTOCOL` (defaults to `http/protobuf`; the X-Ray OTLP endpoint doesn't support gRPC) and `OTEL_EXPORTER_OTLP_ENDPOINT`/`OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` (auto-derived from `AWS_REGION` once Application Signals is off).

---

## ECS Fargate: OTEL Collector Sidecar

### Why a sidecar?

ECS tasks are long-running processes. Instead of embedding a collector inside the app (which would couple concerns and consume app memory), the ADOT collector runs as a **separate container in the same Fargate task**. Containers in the same Fargate task share a network namespace, meaning they can communicate via `localhost`.

### Sidecar container definition

```python
# iac/xray_poc/xray_stack.py
otel_container = task_definition.add_container(
    "OtelCollector",
    image=ecs.ContainerImage.from_registry(
        "public.ecr.aws/aws-observability/aws-otel-collector:latest"
    ),
    command=["--config=/etc/ecs/ecs-default-config.yaml"],
    essential=False,
    environment={"AWS_REGION": Stack.of(self).region},
)
otel_container.add_port_mappings(ecs.PortMapping(container_port=4317))  # gRPC
otel_container.add_port_mappings(ecs.PortMapping(container_port=4318))  # HTTP
```

`essential=False` means the task keeps running if the collector crashes — the app degrades gracefully (losing traces) rather than failing entirely.

### The default ECS config

The command `--config=/etc/ecs/ecs-default-config.yaml` references a config file **baked into the collector image** by AWS. You don't provide this file — it's already there. It configures the collector to:

- **Receive**: OTLP traces on ports 4317 (gRPC) and 4318 (HTTP), *and* legacy X-Ray daemon protocol on UDP port 2000
- **Process**: Batch traces for efficiency
- **Export**: Send traces to AWS X-Ray using the `awsxray` exporter, and metrics to CloudWatch using the `awsemf` exporter

The config (confirmed against the actual [`ecs-default-config.yaml`](https://github.com/aws-observability/aws-otel-collector/blob/main/config/ecs/ecs-default-config.yaml) in the `aws-otel-collector` repo) looks like this:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318
  awsxray:
    endpoint: 0.0.0.0:2000
    transport: udp

processors:
  batch:

exporters:
  awsxray:
    region: ${AWS_REGION}
  awsemf:
    region: ${AWS_REGION}

service:
  pipelines:
    traces:
      receivers: [otlp, awsxray]
      processors: [batch]
      exporters: [awsxray]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [awsemf]
```

The `awsxray` UDP receiver on port 2000 is a compatibility shim for tools that speak the classic X-Ray daemon wire protocol instead of OTLP — that's what `AWS_XRAY_DAEMON_ADDRESS=localhost:2000` on the app container is for (unused fallback, since the app exports via OTLP to port 4317), and it's what Envoy's native X-Ray tracer uses to submit its own segments. See [`docs/envoy.md`](envoy.md).

### App container: ADOT Node.js agent

The Express app loads the ADOT instrumentation agent via `NODE_OPTIONS`, wrapped by a small local bootstrap file instead of requiring the package directly:

```dockerfile
# app-xray/Dockerfile
ENV NODE_OPTIONS="--require /app/otel-bootstrap.js"
```

This is also set (and takes precedence, since ECS task-level environment variables override the image's `ENV` of the same name) in the CDK task definition environment:

```python
"NODE_OPTIONS": "--require /app/otel-bootstrap.js",
```

`otel-bootstrap.js` (`app-xray/otel-bootstrap.js`) requires `@aws/aws-distro-opentelemetry-node-autoinstrumentation/register` itself — same effect as requiring it directly — then reaches into the array of instrumentations it exports to patch `@opentelemetry/instrumentation-http`'s config via its public `setConfig()`/`getConfig()` API. It adds a `requestHook` that renames one specific span: the ECS task-credentials call (`GET http://169.254.170.2/v2/credentials/<id>`) that the AWS SDK makes before every signed request to fetch the task role's temporary credentials. Without this, that call shows up in the X-Ray service map as a bare `169.254.170.2:80` node; with it, the span is renamed and gets a `peer.service` attribute of `ecs-task-credentials`, which is what the AWS X-Ray OTel exporter uses to label a remote node it doesn't otherwise recognize as a named AWS API call. This is unrelated to application logic — it happens on every AWS SDK call regardless of what the app is doing.

The underlying `register` script (whichever way it's loaded) initialises the OTel Node.js SDK and patches:
- `express` — HTTP server spans (each incoming request becomes a span)
- `@aws-sdk/*` — AWS SDK client calls (Lambda invocations become child spans)
- `http`/`https` — outbound HTTP calls
- `undici` — outbound global `fetch()` calls (see [Manual vs. automatic propagation](#manual-vs-automatic-propagation) below — the Lambda layer bundles this instrumentation too, but that alone isn't enough to keep `xray-invoker` connected to the rest of the trace; a manual header is still required there for a different reason)

The agent is configured to send traces to the sidecar via:

```python
"OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4317",
"OTEL_EXPORTER_OTLP_PROTOCOL": "grpc",
```

`localhost:4317` reaches the OTEL collector sidecar because both containers share the Fargate task's network namespace.

### IAM permissions

The ECS task role needs X-Ray write permissions. The collector exports on behalf of the task role:

```python
task_definition.task_role.add_to_policy(
    iam.PolicyStatement(
        actions=[
            "xray:PutTraceSegments",
            "xray:PutTelemetryRecords",
            "xray:GetSamplingRules",
            "xray:GetSamplingTargets",
            "xray:GetSamplingStatisticSummaries",
        ],
        resources=["*"],
    )
)
```

Lambda functions get X-Ray permissions automatically when `tracing=ACTIVE` is set — CDK adds the necessary managed policy.

### Environment variables summary

```
NODE_OPTIONS=--require /app/otel-bootstrap.js        # wraps the ADOT register script, see above
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # sidecar gRPC endpoint
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_SERVICE_NAME=xray-frontend                      # appears in X-Ray service map
OTEL_PROPAGATORS=xray                                # X-Ray trace context propagation
AWS_XRAY_DAEMON_ADDRESS=localhost:2000               # fallback daemon address; also where Envoy's native tracer sends segments, see docs/envoy.md
OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true
```

`xray-idp` (`app-idp/`) uses the same collector-sidecar pattern with the same environment variables (`OTEL_SERVICE_NAME=xray-idp`), minus the `otel-bootstrap.js` wrapper — it requires `@aws/aws-distro-opentelemetry-node-autoinstrumentation/register` directly, since it has no Envoy sidecar and no need for the credentials-span renaming.

---

## Trace Context Propagation

For a trace to span the full chain (Invoker → Envoy → ECS → Dog Fetcher → S3 Writer, with a side branch to idp), each hop must pass the trace context forward.

`OTEL_PROPAGATORS=xray` tells the ADOT agent to use **AWS X-Ray trace context format** (`X-Amzn-Trace-Id` header) when propagating context over HTTP and when invoking Lambda functions. This is the format X-Ray natively understands, so traces from different services stitch together into a single service map in the AWS Console.

The propagation flow:

```
xray-invoker Lambda
  sets X-Amzn-Trace-Id header on HTTP call to the ALB
  → Envoy (native X-Ray tracer) receives header, creates its own segment,
    re-parents the header before forwarding to the app - see "Envoy" below
    → ECS app (xray-frontend) receives header, continues the trace
        side-call: GET idp.xray.local:3000/idp/health (CloudMap, bypasses the ALB)
        → xray-idp continues the trace, unrelated to the dog-fetch below
      invokes xray-dog-fetcher Lambda (AWS SDK InvokeCommand)
      → xray-dog-fetcher Lambda continues the trace
        invokes xray-s3-writer Lambda directly (AWS SDK InvokeCommand)
        → xray-s3-writer Lambda continues the trace
```

There is no SNS in this chain — `xray-dog-fetcher` calls `xray-s3-writer` with a plain `LambdaClient` `InvokeCommand`, same as the ECS app calls `xray-dog-fetcher`.

### Envoy: participating in the trace

A plain reverse proxy with no tracing configured is invisible to X-Ray — it forwards the `X-Amzn-Trace-Id` header unchanged (any HTTP proxy does that by default; headers it doesn't recognize just pass through), but it never creates a segment of its own, so it never shows up as a node in the service map. Making Envoy actually *participate* in the trace — rather than just transparently carrying the header through it — takes one extra piece of config beyond the pass-through routing: a native tracer provider on the HTTP connection manager (`x-ray/envoy/envoy.yaml`):

```yaml
tracing:
  provider:
    name: envoy.tracers.xray
    typed_config:
      "@type": type.googleapis.com/envoy.config.trace.v3.XRayConfig
      segment_name: envoy-proxy
      daemon_endpoint:
        protocol: UDP
        address: 127.0.0.1
        port_value: 2000
```

`envoy.tracers.xray` is Envoy's built-in X-Ray tracer (the same mechanism AWS App Mesh uses under the hood) — unlike Envoy's generic `envoy.tracers.opentelemetry` provider, it natively reads and writes the `X-Amzn-Trace-Id` header format, so it stitches into the same trace as everything else here instead of starting a disconnected W3C-propagated trace of its own. It sends its segment via the classic UDP X-Ray-daemon protocol to `127.0.0.1:2000` — the OTel collector sidecar's `awsxray` receiver described above, which was already running for the `AWS_XRAY_DAEMON_ADDRESS` fallback but wasn't previously being used by anything.

`daemon_endpoint` has to be spelled out explicitly. Envoy's own docs say it "defaults to 127.0.0.1:2000" when unset, but that default apparently only applies at a different layer than an entirely-omitted YAML field — leaving it out produced `X-Ray daemon endpoint must be a UDP socket address` from `envoy --mode validate`. Caught locally before ever touching the live stack; see [`docs/envoy.md`](envoy.md) for how that was verified.

Once configured, Envoy generates a real child segment on every request and **re-parents the trace before forwarding it on** — verified locally by sending a request with a fake `Parent` ID and observing the outgoing request to the app carry a *different* `Parent` (Envoy's own new segment ID), same `Root` (trace ID). That's the mechanism that makes it appear as a genuine hop between the ALB and the app in the X-Ray service map, not just a pass-through.

### Manual vs. automatic propagation

Most of the chain is automatic — the ADOT auto-instrumentation patches the AWS SDK v3 client so trace context is injected into the outgoing Lambda `Invoke` call for free:

- ECS app → `xray-dog-fetcher` (`app-xray/src/app.ts`)
- `xray-dog-fetcher` → `xray-s3-writer` (`lambda/xray-dog-fetcher/src/handler.ts`)

Neither of these handlers touches trace headers directly.

The one exception is the first hop, `xray-invoker` → ALB, which **is done manually in app code** (`lambda/xray-invoker/src/handler.ts`):

```ts
const traceHeader = process.env._X_AMZN_TRACE_ID;
const response = await fetch(url, {
  headers: { ...(traceHeader ? { "X-Amzn-Trace-Id": traceHeader } : {}) },
});
```

This is necessary because Node's global `fetch()` is backed by `undici`, and — despite what you'd expect — the **Lambda ADOT layer's** own instrumentation of it isn't enough on its own to keep `xray-invoker` connected to the rest of the trace. Without this explicit header, `xray-invoker`'s official X-Ray segment (the one driven by `tracing=lambda_.Tracing.ACTIVE` and Lambda's `_X_AMZN_TRACE_ID` env var) ends up **orphaned from everything downstream of it**.

This was tested live end-to-end (2026-09-01, against the **legacy** `aws-otel-nodejs-amd64-ver-1-30-2:6` layer, before the migration to `AWSOpenTelemetryDistroJs` described earlier in this doc) by deploying, removing this header, invoking, and inspecting the resulting trace via `aws xray batch-get-traces`:

- **With the header removed**: `xray-invoker`'s own Lambda-native segment landed under one trace ID, while the entire downstream chain — Envoy, `xray-frontend`, `xray-idp`, `xray-dog-fetcher`, `xray-s3-writer` — landed correctly parented under a *different* trace ID. So the downstream `undici` propagation genuinely does work (confirming the layer does bundle `@opentelemetry/instrumentation-undici`, verified separately by unpacking the layer zip and finding `UndiciInstrumentation` subscribing to the `undici:request:create`/`undici:client:sendHeaders`/`undici:request:headers` diagnostics channels) — but the OTel SDK's own X-Ray ID generator was minting a *fresh* trace ID for that outbound span instead of inheriting the one Lambda's active-tracing runtime already established via `_X_AMZN_TRACE_ID`. The net effect in the X-Ray console: `xray-invoker`'s real invocation trace shows no downstream hops at all.
- **With the header restored**: a single trace contains all 10 segments, correctly parented from `xray-invoker`'s native segment straight through to `xray-s3-writer`.

So the manual header stays. This is specific to how Lambda's built-in active tracing and the ADOT/OTel SDK's own trace-ID generation interact for the *first* hop out of a Lambda — it's not a general Node.js/OTel limitation: `xray-frontend`'s own side-call to idp (`checkIdpHealth()` in `app-xray/src/app.ts`) uses plain `fetch()` too, with no manual header handling, and it propagates correctly, because ECS tasks have no equivalent Lambda-native active-tracing segment to stay in sync with — there's only ever the one, OTel-SDK-generated trace ID for that leg. The npm-installed `@aws/aws-distro-opentelemetry-node-autoinstrumentation` package used by the ECS apps bundles `@opentelemetry/instrumentation-undici` too, same as the Lambda layer, so `fetch()` calls made from `app-xray` or `app-idp` are covered automatically with no manual step.

**Re-verified against the new `AWSOpenTelemetryDistroJs` layer (2026-09-02)**, same live-deploy-and-inspect method: all 19 segments of a real invocation's trace landed under a single trace ID, correctly parented end-to-end — `xray-invoker`'s Lambda-native root segment → its own OTel-SDK-generated outbound `GET` span → `envoy-proxy` → `xray-frontend` → `xray-idp`/`xray-dog-fetcher` (each with their own native `Init`/`Overhead` subsegments) → `xray-s3-writer`. No orphaning, same as the legacy layer with the header present. `xray-invoker`'s handler code is unchanged by this migration, so this is the expected result rather than a surprise — the manual header stays required for the same underlying reason either way.

---

## Viewing Traces

After triggering the invoker Lambda, traces appear in:

- **AWS Console → X-Ray → Traces** — timeline view of each individual trace
- **AWS Console → X-Ray → Service Map** — visual graph of the full call chain with latency and error rates
- **AWS Console → CloudWatch → Application Signals** — if `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true` is set
