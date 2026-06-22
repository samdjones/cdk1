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

- Outbound HTTP/HTTPS requests (including `fetch()` calls to dog.ceo)
- AWS SDK v3 client calls (SNS `PublishCommand`, S3 `PutObjectCommand`)
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

- **Receive**: OTLP traces on ports 4317 (gRPC) and 4318 (HTTP)
- **Process**: Batch traces for efficiency
- **Export**: Send traces to AWS X-Ray using the `awsxray` exporter, and metrics to CloudWatch using the `awsemf` exporter

The config looks roughly like this (for reference — it's inside the image):

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

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
      receivers: [otlp]
      processors: [batch]
      exporters: [awsxray]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [awsemf]
```

### App container: ADOT Node.js agent

The Express app loads the ADOT instrumentation agent via `NODE_OPTIONS`:

```dockerfile
# app-xray/Dockerfile
ENV NODE_OPTIONS="--require @aws/aws-distro-opentelemetry-node-agent/register"
```

This is also set in the CDK task definition environment:

```python
"NODE_OPTIONS": "--require @aws/aws-distro-opentelemetry-node-agent/register",
```

The `register` script initialises the OTel Node.js SDK and patches:
- `express` — HTTP server spans (each incoming request becomes a span)
- `@aws-sdk/*` — AWS SDK client calls (Lambda invocations become child spans)
- `http`/`https`/`fetch` — outbound HTTP calls

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
NODE_OPTIONS=--require @aws/aws-distro-opentelemetry-node-agent/register
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317   # sidecar gRPC endpoint
OTEL_EXPORTER_OTLP_PROTOCOL=grpc
OTEL_SERVICE_NAME=xray-frontend                      # appears in X-Ray service map
OTEL_PROPAGATORS=xray                                # X-Ray trace context propagation
AWS_XRAY_DAEMON_ADDRESS=localhost:2000               # fallback daemon address
OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true
```

---

## Trace Context Propagation

For a trace to span the full chain (Invoker → ECS → Dog Fetcher → S3 Writer), each hop must pass the trace context forward.

`OTEL_PROPAGATORS=xray` tells the ADOT agent to use **AWS X-Ray trace context format** (`X-Amzn-Trace-Id` header) when propagating context over HTTP and when invoking Lambda functions. This is the format X-Ray natively understands, so traces from different services stitch together into a single service map in the AWS Console.

The propagation flow:

```
xray-invoker Lambda
  sets X-Amzn-Trace-Id header on HTTP call to ALB
  → ECS app receives header, continues the trace
    sets X-Amzn-Trace-Id on Lambda invoke payload
    → xray-dog-fetcher Lambda continues the trace
      sets X-Amzn-Trace-Id on SNS publish message attributes
      → xray-s3-writer Lambda continues the trace
```

---

## Viewing Traces

After triggering the invoker Lambda, traces appear in:

- **AWS Console → X-Ray → Traces** — timeline view of each individual trace
- **AWS Console → X-Ray → Service Map** — visual graph of the full call chain with latency and error rates
- **AWS Console → CloudWatch → Application Signals** — if `OTEL_AWS_APPLICATION_SIGNALS_ENABLED=true` is set
