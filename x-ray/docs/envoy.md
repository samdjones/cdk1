# Envoy Sidecar

This document explains the Envoy proxy sitting in front of the `xray-frontend` app container, its configuration (`x-ray/envoy/`), and how it was made to participate in X-Ray tracing rather than just pass requests through invisibly.

## What it does

Before Envoy, the ALB targeted the `xray-frontend` app container directly. Now it targets Envoy, which forwards everything to the app on localhost:

```
ALB → Envoy (:8080) → xray-frontend app (:8000)
```

It's a pure pass-through — no auth, no rate limiting, no request/response transformation. The point of this stack is to demonstrate the wiring, not to build a real gateway.

## Why distroless

`x-ray/envoy/Dockerfile` builds from `docker.io/envoyproxy/envoy-distroless:v1.31-latest` rather than the standard `envoyproxy/envoy` image. The distroless variant strips out the shell and package manager, leaving just the `envoy` binary and its runtime dependencies — smaller image, smaller attack surface, appropriate for a container that does nothing but proxy traffic on a static config file.

One consequence: distroless has no shell, so there's no `docker-entrypoint.sh` to fall back on. The Dockerfile sets `ENTRYPOINT`/`CMD` to invoke the binary directly instead of relying on whatever the base image's default entrypoint does:

```dockerfile
ENTRYPOINT ["/usr/local/bin/envoy"]
CMD ["-c", "/etc/envoy/envoy.yaml"]
```

### Fully-qualified image reference

`deploy.sh` runs CDK with `CDK_DOCKER=podman`. Podman here has no unqualified-search registries configured, so a bare `FROM envoyproxy/envoy-distroless:...` fails to resolve at build time (`short-name did not resolve to an alias`) — reproduced locally before it became a live deploy failure. The Dockerfile uses the fully-qualified `docker.io/envoyproxy/envoy-distroless:v1.31-latest`, matching the existing convention already used for the OTel collector image (`public.ecr.aws/aws-observability/aws-otel-collector:latest`) in `xray_stack.py`.

## Config walkthrough (`x-ray/envoy/envoy.yaml`)

**Listener** — `0.0.0.0:8080`, one filter chain running `envoy.filters.network.http_connection_manager`.

**Route** — a single catch-all route to `app_cluster`, with an explicit 60-second timeout:

```yaml
route:
  cluster: app_cluster
  timeout: 60s
```

Envoy's default route timeout is 15 seconds. The app's `/fetch-dog` handler chains ECS → Lambda → dog.ceo → Lambda → S3, which can run past that on a slow request, while the ALB's own idle timeout is 60 seconds — so 15s would make Envoy the tightest, least visible timeout in the chain (a silent 504 mid-trace). 60s matches the ALB instead.

**Cluster** — `app_cluster` is `STATIC`, one endpoint at `127.0.0.1:8000`. Static and loopback because Envoy and the app share the same Fargate task's network namespace (`awsvpc` mode) — no service discovery needed, the app is always reachable at localhost.

**Admin** — bound to `127.0.0.1:9901`, not exposed outside the task.

## CDK wiring (`xray_stack.py`)

Envoy is added as another container on the same task definition as the app and the OTel collector sidecar, essential (if it dies, the task should be considered unhealthy):

```python
envoy_container = task_definition.add_container(
    "EnvoyProxy",
    image=ecs.ContainerImage.from_asset("envoy"),
    logging=ecs.LogDrivers.aws_logs(stream_prefix="xray-envoy"),
    essential=True,
)
envoy_container.add_port_mappings(ecs.PortMapping(container_port=8080))

task_definition.default_container = envoy_container
```

That last line is the important one: with two essential containers on the task (app + Envoy), CDK can no longer infer which one the ALB target group should point at, so it has to be set explicitly. Once set, the ALB registers against Envoy's container/port instead of the app's.

## Tracing: `envoy.tracers.xray`

A proxy with no tracer configured is invisible to X-Ray by default — it forwards `X-Amzn-Trace-Id` unchanged (ordinary HTTP header passthrough, verified locally), but never creates a segment of its own. Making it show up as a real node in the trace took one more block:

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

- **`envoy.tracers.xray`**, not `envoy.tracers.opentelemetry` — this is Envoy's built-in X-Ray tracer (the same one App Mesh uses). It natively reads/writes the `X-Amzn-Trace-Id` header format, so it stitches into the *same* trace as everything else. The generic OTel tracer provider defaults to W3C `traceparent` propagation and would have produced a second, disconnected trace.
- **`daemon_endpoint`** sends segments via the classic UDP X-Ray-daemon wire protocol to the OTel collector sidecar's `awsxray` receiver on `127.0.0.1:2000` — see [`docs/xray-collector-setup.md`](xray-collector-setup.md) for that receiver's config. This field had to be spelled out explicitly: Envoy's own docs describe a "defaults to 127.0.0.1:2000" behavior for an *unset* field, but leaving it out entirely produced `X-Ray daemon endpoint must be a UDP socket address` from Envoy's own config validator (`envoy --mode validate`) — caught locally, before it ever reached a live deploy.
- **`segment_name: envoy-proxy`** — required field, this is the name that shows up in the X-Ray service map.

## How it was verified

Before deploying, the built image was run locally with `--network host` (to mimic the shared network namespace Fargate `awsvpc` mode gives sibling containers) against a small Python stub server that echoes request headers back. Two things were checked directly against the real `envoy-distroless` binary, not assumed from docs:

1. **Config validity** — `envoy --mode validate -c envoy.yaml` catches schema errors (like the `daemon_endpoint` issue above) without needing a running collector or a deploy.
2. **Re-parenting behavior** — a request was sent with a fake `X-Amzn-Trace-Id` header (`Parent=0000000000000001`). The request that Envoy forwarded to the backend carried a *different* `Parent` (Envoy's own freshly-generated segment ID) while keeping the same `Root` (trace ID unchanged). That's the mechanism that makes Envoy a real, correctly-nested hop in the trace rather than just a transparent pass-through — proof the tracer is active even without a real X-Ray daemon listening on the loopback UDP port locally (the send is fire-and-forget UDP, so the app-facing behavior — the header rewrite — is what's checkable without one).

After deploying, a real trace confirmed the same thing end-to-end: the `envoy-proxy` segment sits between the invoker Lambda's outbound call and the `xray-frontend` segment, both under the same trace ID.
