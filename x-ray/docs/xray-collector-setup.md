# X-Ray Collector Setup: ECS and Lambda

This document explains how OpenTelemetry traces are collected and exported to AWS X-Ray in the X-Ray POC stack.

## Overview

Both the ECS Fargate service and the Lambda functions use the **AWS Distro for OpenTelemetry (ADOT)** to collect and export traces. ADOT is AWS's distribution of the OpenTelemetry project — it bundles the OTel SDK, auto-instrumentation agents, and a collector pre-configured to work with AWS services including X-Ray.

The two environments use different ADOT packaging because of their different execution models:

| | Lambda | ECS Fargate |
|---|---|---|
| Collector packaging | Lambda Layer | Sidecar container |
| Auto-instrumentation | `otel-handler` exec wrapper | Node.js agent via `NODE_OPTIONS` |
| Collector config | Built into layer | `ecs-default-config.yaml` (baked into image) |
| Export destination | X-Ray (via ADOT layer default) | X-Ray (via OTEL collector sidecar) |

---

## Lambda: ADOT Lambda Layer

### How it works

Lambda functions are short-lived processes — there's no persistent sidecar to run alongside them. Instead, ADOT is packaged as a **Lambda Layer** that contains both:

1. A **collector binary** (a stripped-down OTel Collector that runs in-process)
2. An **auto-instrumentation agent** for Node.js that patches the AWS SDK and HTTP clients

The layer is attached via CDK:

```python
# iac/xray_poc/xray_stack.py
adot_layer = lambda_.LayerVersion.from_layer_version_arn(
    self,
    "AdotLayer",
    f"arn:aws:lambda:{Stack.of(self).region}:901920570463:layer:aws-otel-nodejs-amd64-ver-1-18-1:4",
)
```

The layer ARN `901920570463` is AWS's own account — this is a publicly available managed layer, not something you build yourself.

**`xray-dog-fetcher` is the exception**: it uses a self-owned copy of this same layer instead of the shared ARN above, to demonstrate how to avoid a live cross-account layer reference at deploy time (some environments block attaching layers published by a foreign account, and can't make any AWS API call as part of their own build/deploy to fetch one on the fly either). `lambda/xray-dog-fetcher/otel-layer.zip` is a **vendored, checked-in artifact** — `frontend_stack.py`'s `AdotLayerDogFetcher` builds a normal `LayerVersion` from it via `Code.from_asset` (CDK uploads a `.zip` path as-is, no local unzip/rezip) instead of `from_layer_version_arn`. The zip isn't downloaded as part of `deploy.sh`/prod's own pipeline; it's refreshed manually, out-of-band, by running `lambda/xray-dog-fetcher/download-otel-layer.sh` on a machine that does have AWS credentials (`aws lambda get-layer-version` against the public ARN to get a presigned URL, then fetch it) whenever the pinned layer version needs bumping, then committing the result — the same way you'd bump any other vendored dependency. The runtime behavior is identical to the ARN-based layer — it's still a Layer mounted at `/opt` with the same internal layout, since a Lambda Extension (the embedded collector binary) can only be discovered by Lambda from `/opt/extensions/`, which only a Layer can populate. `xray-invoker` and `xray-s3-writer` keep using the AWS-managed ARN for contrast.

### The exec wrapper: `AWS_LAMBDA_EXEC_WRAPPER`

The key to zero-code-change instrumentation is this environment variable:

```python
"AWS_LAMBDA_EXEC_WRAPPER": "/opt/otel-handler",
```

Lambda supports an exec wrapper mechanism: before running your handler, Lambda executes the binary at the path in `AWS_LAMBDA_EXEC_WRAPPER`, which in turn starts your handler. The `/opt/otel-handler` script (provided by the layer at `/opt/`) does the following:

1. Starts the embedded ADOT Collector in a background thread
2. Sets `NODE_OPTIONS=--require /opt/nodejs/node_modules/@aws/aws-distro-opentelemetry-node-agent/register` to load the Node.js auto-instrumentation agent before your code runs
3. Starts your handler process as normal

This means your handler code requires **no changes** — all AWS SDK calls, HTTP requests, and Lambda invocations are automatically traced.

### Active tracing

CDK enables X-Ray active tracing on each Lambda:

```python
tracing=lambda_.Tracing.ACTIVE,
```

This tells the Lambda service to create an X-Ray trace segment for every invocation and pass the `_X_AMZN_TRACE_ID` header into the execution environment. The ADOT layer picks this up and uses it as the root segment, so all child spans (SDK calls, HTTP calls) nest under the same trace.

### What gets traced automatically

- Outbound HTTP/HTTPS requests
- AWS SDK v3 client calls (Lambda `InvokeCommand`, S3 `PutObjectCommand`)
- The Lambda invocation itself (as the root segment)

### Environment variables summary

```
AWS_LAMBDA_EXEC_WRAPPER=/opt/otel-handler   # activates the layer's wrapper
OTEL_PROPAGATORS=xray                        # use X-Ray trace context format
OTEL_TRACES_EXPORTER=otlp                    # export via OTLP to embedded collector
OTEL_EXPORTER_OTLP_PROTOCOL=grpc             # gRPC transport to collector
OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true    # enable Application Signals metrics
```

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
- `undici` — outbound global `fetch()` calls (see [Manual vs. automatic propagation](#manual-vs-automatic-propagation) below — this matters because it's *not* true of the Lambda ADOT layer)

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

This is necessary because Node's global `fetch()` is backed by `undici`, and the **Lambda ADOT layer's** bundled instrumentation set doesn't cover it — without this explicit header, the trace would break (or restart) at this hop.

This is specific to the Lambda layer, not a general Node.js/OTel limitation: `xray-frontend`'s own side-call to idp (`checkIdpHealth()` in `app-xray/src/app.ts`) uses plain `fetch()` too, with no manual header handling, and it propagates correctly — confirmed in a real trace. The npm-installed `@aws/aws-distro-opentelemetry-node-autoinstrumentation` package used by the ECS apps bundles `@opentelemetry/instrumentation-undici` by default, so `fetch()` calls made from `app-xray` or `app-idp` are covered automatically; the Lambda layer (`aws-otel-nodejs-amd64-ver-1-18-1`) is a different, older bundled distribution that isn't.

---

## Viewing Traces

After triggering the invoker Lambda, traces appear in:

- **AWS Console → X-Ray → Traces** — timeline view of each individual trace
- **AWS Console → X-Ray → Service Map** — visual graph of the full call chain with latency and error rates
- **AWS Console → CloudWatch → Application Signals** — if `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true` is set
