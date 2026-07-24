# CloudMap Service Discovery

This document explains the AWS Cloud Map setup that lets `xray-frontend` reach `xray-idp` directly, without going through the public ALB.

## Why

`xray-idp` is reachable two ways:

1. **Publicly, via the shared ALB** — `/idp` and `/idp/*` are path-routed to it. This is how an external client (or the ALB health check) reaches it.
2. **Privately, via CloudMap** — `xray-frontend` calls `http://idp.xray.local:3000/idp/health` directly, over the VPC's internal network, before invoking the dog-fetcher Lambda on every `/fetch-dog` request.

The second path exists specifically so that service-to-service traffic inside the VPC doesn't have to round-trip out through a public load balancer and back in — which is what CloudMap is for. Routing an internal call through the public ALB would have worked too, but it's the kind of pattern that's fine in a two-hop demo and actively bad practice at any real scale (extra latency, extra public attack surface, extra failure mode if the ALB or its security group ever changes).

## Namespace

```python
cloud_map_namespace = servicediscovery.PrivateDnsNamespace(
    self,
    "XrayNamespace",
    name="xray.local",
    vpc=vpc,
)
```

A `PrivateDnsNamespace` creates a private Route 53 hosted zone that only resolves inside the associated VPC — `xray.local` isn't a real public domain and isn't meant to be; it's not resolvable from outside the VPC at all.

## Service registration

Only `xray-idp` is registered — `xray-frontend` doesn't need to be discovered by anything, since it's the only caller in this graph:

```python
idp_service = ecs.FargateService(
    self,
    "XrayIdpService",
    cluster=idp_cluster,
    task_definition=idp_task_definition,
    desired_count=1,
    cloud_map_options=ecs.CloudMapOptions(
        name="idp",
        cloud_map_namespace=cloud_map_namespace,
        dns_record_type=servicediscovery.DnsRecordType.A,
        container_port=3000,
    ),
    health_check_grace_period=Duration.seconds(60),
)
```

This registers `idp.xray.local` as a DNS name resolving to the running task's ENI IP address, kept in sync by ECS as tasks are replaced.

### Why an A record, not SRV

CloudMap+ECS integrations often default to `SRV` records, because `SRV` encodes the port as well as the address — important when a service runs behind a dynamic host-mapped port (bridge networking on EC2-backed ECS, for instance). None of that applies here: Fargate always runs in `awsvpc` mode, where every task gets its own ENI and the container port is fixed and known in advance (3000). A plain `A` record is simpler and sufficient — the frontend just needs the fixed port baked in alongside the resolved name, which is exactly what `IDP_URL` does:

```python
idp_url = f"http://{idp_cloud_map_name}.{cloud_map_namespace.namespace_name}:{idp_container_port}"
app_container.add_environment("IDP_URL", idp_url)
```

(`http://idp.xray.local:3000`, added to the frontend's container environment after the fact via `add_environment()`, since the frontend's `app_container` is constructed earlier in the stack, before `idp_service` exists.)

## Security group

CloudMap only provides DNS resolution — it doesn't open any network path by itself. The ALB's target-group wiring (`listener.add_targets(..., targets=[idp_service])`) automatically opens ingress on idp's security group **from the ALB**, but the frontend's direct CloudMap call bypasses the ALB entirely, so it needs its own explicit rule:

```python
idp_service.connections.allow_from(
    frontend_service,
    ec2.Port.tcp(idp_container_port),
    "Allow the frontend to call idp /idp/health via CloudMap",
)
```

Without this, the health-check side-call would connect-timeout — silently, since the frontend treats it as best-effort and only logs a warning, never failing the request. (One gotcha hit while adding this: the rule description originally contained an apostrophe — `idp's` — which EC2 rejects. Security group rule descriptions only accept `a-zA-Z0-9. _-:/()#,@[]+=&;{}!$*`; the deploy failed with `Invalid rule description` and rolled back cleanly on its own.)

## Usage

`app-xray/src/app.ts`'s `checkIdpHealth()` runs before every `/fetch-dog` request:

```ts
const IDP_URL = process.env.IDP_URL;

async function checkIdpHealth(): Promise<void> {
  if (!IDP_URL) return;
  try {
    const response = await fetch(`${IDP_URL}/idp/health`);
    console.log(`idp health check: ${response.status}`);
  } catch (err) {
    console.error("idp health check failed:", err);
  }
}
```

It's a side-call, not a readiness gate — a failure is logged, not fatal, and doesn't block the actual dog-fetching work. See [`docs/xray-collector-setup.md`](xray-collector-setup.md#manual-vs-automatic-propagation) for how this call still ends up correctly nested in the same X-Ray trace despite using plain `fetch()`.
