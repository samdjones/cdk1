# ALB POC

Disposable AWS demo of an Application Load Balancer doing path-based routing
across 3 independent ECS Fargate backends.

## What It Does

An internal (not internet-facing) ALB listener routes requests to one of 3
backends by path:

| Path         | Backend   |
| ------------ | --------- |
| `/main/*`    | `main`    |
| `/auth/*`    | `auth`    |
| everything else (`*`) | `default` |

Each backend is a minimal Express app that reports which service handled the
request, so routing is easy to verify with `curl`. The ALB has no public IP
and is not reachable from the internet — the only way in is an SSM
Session Manager port-forward through a small bastion instance, so there's no
need for application-level auth on an otherwise disposable experimental stack.

## Architecture

```
Your laptop
   │  aws ssm start-session (port forward, localhost:8080 → ALB:80)
   ▼
SSM Bastion (EC2, private subnet, zero inbound security group rules)
   │
   ▼
ALB Listener (port 80, internal only — no public IP)
   ├── /main/*  ──▶  main backend    (ECS Fargate)
   ├── /auth/*  ──▶  auth backend    (ECS Fargate)
   └── *        ──▶  default backend (ECS Fargate, listener default action)
```

No tracing, Lambda, or S3 — this demo is focused purely on ALB path-based
routing.

## Prerequisites

- Node.js 22+
- Python 3.12+
- AWS CLI configured with credentials
- AWS CDK CLI (`npm install -g aws-cdk`, or via the shared root `package.json`)
- Docker
- [Session Manager plugin](https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)
  for the AWS CLI (required for `aws ssm start-session`):
  - macOS: `brew install --cask session-manager-plugin`
  - Linux (Debian/Ubuntu): download and `dpkg -i` the AWS-hosted `.deb`
  - Verify with `session-manager-plugin` — it should print a version banner

## Deploy / Destroy

```bash
./deploy.sh                                                    # Build all 3 apps + deploy
./destroy.sh                                                   # Destroy AlbPocStack
```

The bastion (`t3.nano`) is a small continuous EC2 cost while the stack is
deployed — destroy the stack when you're done with it, as usual.

## Access the ALB

The ALB is internal-only, so reach it via an SSM port-forward through the
bastion. Two scripts automate this:

- **`./connect.sh [local-port]`** — looks up the deployed stack's
  `BastionInstanceId`/`AlbDnsName` outputs itself, then opens an SSM
  Session Manager port-forward tunnel (`localhost:<local-port>` → the
  internal ALB on port 80). Defaults to local port `8080`. Runs in the
  foreground — leave it running and use a second terminal. Press Ctrl+C
  to close the tunnel.
- **`./test-routes.sh [local-port]`** — run in that second terminal while
  `connect.sh` is open. Curls all 3 routing rules through the tunnel
  (`/main/*`, `/auth/*`, and the catch-all) and prints PASS/FAIL against
  the expected backend for each.

```bash
# terminal 1
./connect.sh              # opens localhost:8080 -> internal ALB:80

# terminal 2
./test-routes.sh          # exercises all 3 path-routing rules
```

Example `test-routes.sh` output:

```
=== ALB POC Route Tests (via http://localhost:8080) ===
(requires ./connect.sh 8080 running in another terminal)

PASS  /main/foo -> {"service":"main","path":"/main/foo"}
PASS  /auth/bar -> {"service":"auth","path":"/auth/bar"}
PASS  /anything -> {"service":"default","path":"/anything"}

All routes OK.
```

Both scripts default to region `us-east-1` (matching `iac/app_alb.py`) —
override with the `AWS_REGION` env var if your stack is elsewhere. Right
after a fresh deploy, the bastion can take under a minute to register with
SSM — retry `connect.sh` if it fails immediately.

If you'd rather run the underlying command by hand instead of using
`connect.sh`, get `BastionInstanceId` and `AlbDnsName` from `aws
cloudformation describe-stacks --stack-name AlbPocStack`, then:

```bash
aws ssm start-session --target <bastion-instance-id> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters '{"host":["<alb-dns>"],"portNumber":["80"],"localPortNumber":["8080"]}' \
  --region us-east-1
```

## How the CDK Stack Is Configured

Everything lives in `iac/alb_poc/alb_stack.py` (`AlbPocStack`). Walking
through it top to bottom:

**VPC** — `ec2.Vpc` with 2 AZs, 1 NAT gateway, and two subnet groups per AZ:
`Public` (has a route to the internet gateway) and `Private`
(`PRIVATE_WITH_EGRESS` — outbound-only via the NAT gateway, no direct
inbound path from the internet). Everything that actually runs — the ALB,
the bastion, and all 3 ECS services — is placed in the `Private` subnets;
the `Public` subnets exist only to host the NAT gateway.

**ECS Cluster** — a plain `ecs.Cluster` with Container Insights on, shared
by all 3 backend services.

**Bastion (`ec2.Instance`)** — a `t3.nano` running Amazon Linux 2023
(`ec2.MachineImage.latest_amazon_linux2023()`, which ships with the SSM
agent preinstalled), placed in the private subnets, with
`require_imdsv2=True`. Two things make it safe to leave running with no
inbound firewall holes at all:
- No inbound security group rules are ever added to it — CDK's default
  `ec2.Instance` security group starts with zero ingress rules, and nothing
  in the stack adds one. SSM Session Manager doesn't need any — the agent
  on the instance polls *outbound* to the SSM service, so the instance
  never needs to accept a connection.
- `bastion.role.add_managed_policy(...AmazonSSMManagedInstanceCore...)`
  attaches the one managed policy that lets the SSM service manage/target
  this instance and lets Session Manager open a channel to it.

**ALB (`elbv2.ApplicationLoadBalancer`)** — created with
`internet_facing=False` and pinned to the private subnets, so it gets no
public IP at all (CDK also sets `deny_all_igw_traffic=True` by default for
internal load balancers as a second layer). The listener is created with
`alb.add_listener("Listener", port=80, open=False)` — the `open=False` is
what stops CDK from adding its usual automatic `0.0.0.0/0` ingress rule.
Immediately after, `alb.connections.allow_from(bastion, ec2.Port.tcp(80),
...)` adds the *only* ingress rule the ALB's security group has: port 80,
source = the bastion's security group. Nothing else, from anywhere, can
reach the ALB.

**Backends (`add_backend(name)`)** — a small helper called once each for
`main`, `auth`, `default`. For each, it builds a `FargateTaskDefinition`
(256 CPU / 512 MiB), a container from `ecs.ContainerImage.from_asset(f"app/{name}")`
(so it Docker-builds straight from `app/main/`, `app/auth/`,
`app/default/`) with a `SERVICE_NAME` env var baked in, and a
`FargateService` running it. None of these set `assign_public_ip`, so
CDK's default placement puts them in the private subnets too — they were
never reachable from the internet even before this ALB became internal.

**Path-based routing** — three `listener.add_targets(...)` calls create the
routing rules:
- `MainTargetGroup` — `priority=10`, `conditions=[ListenerCondition.path_patterns(["/main/*"])]`
- `AuthTargetGroup` — `priority=20`, same pattern for `/auth/*`
- `DefaultTargetGroup` — no `priority`/`conditions` at all, which is what
  makes CDK wire it up as the listener's **default action** instead of a
  numbered rule — i.e. the catch-all for every path that doesn't match
  `/main/*` or `/auth/*`. Priority numbers just need to be unique and
  determine evaluation order (lower first); `10`/`20` leaves room to slot
  more rules in between later without renumbering everything.

Each target group also gets a health check (`path="/health"`,
`healthy_http_codes="200"`), which is what each backend's `/health` route
in `app/<name>/src/app.ts` exists to satisfy.

**Outputs** — `AlbDnsName` (the internal DNS name, used as the `host`
parameter for the SSM port-forward) and `BastionInstanceId` (used as the
`--target` for `aws ssm start-session`) — both consumed automatically by
`connect.sh`.

## Repository Structure

```
alb/
├── app/
│   ├── main/          # ECS Fargate backend for /main/*
│   ├── auth/           # ECS Fargate backend for /auth/*
│   └── default/         # ECS Fargate backend for everything else
├── iac/
│   ├── alb_poc/        # AlbPocStack CDK definition (VPC, ALB, bastion, ECS)
│   └── app_alb.py       # CDK entry point
├── ci/
│   ├── docker_build.sh
│   └── run_unit_tests.sh
├── deploy.sh
├── destroy.sh
├── connect.sh           # Open the SSM port-forward tunnel to the ALB
└── test-routes.sh       # Exercise all 3 path-routing rules through the tunnel
```

This demo shares the repo-root `package.json` (the `aws-cdk` CLI
devDependency, used via `npx`) with the sibling `x-ray/` demo — see the
[repo root README](../README.md).
