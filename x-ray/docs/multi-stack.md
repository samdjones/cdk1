# Multi-Stack Split

This document explains why the x-ray demo deploys as three CloudFormation stacks (`XraySharedStack`, `XrayIdpStack`, `XrayFrontendStack`) instead of one, and the CDK mechanics a shared ALB across stack boundaries actually requires - several of which aren't obvious from the API surface and only showed up as real failures against a live deploy.

## Why split it at all

Honestly: for a demo this size, a single stack (what this repo had until now) works fine. The split exists for learning purposes, not because the previous single-stack version had a real problem. The one concrete thing it does buy, observed directly in this repo's own history: with everything in one stack, every deploy pays for the full sequential wait (idp stabilizes, *then* frontend redeploys) even when only one side actually changed, and a bad change to either service risks a rollback that has to walk the entire changeset. Splitting means `xray-idp` can redeploy without CloudFormation even evaluating `xray-frontend`'s resources, and each stack gets its own independent rollback boundary.

The cost is everything below - shared resources (VPC, ALB, CloudMap namespace) become cross-stack references, which are stickier to change and come with real, sometimes-surprising mechanical constraints.

## The dependency graph

```
XraySharedStack  (VPC, ALB + listener, CloudMap namespace)
      ↑
XrayIdpStack  (idp cluster/task/service)
      ↑
XrayFrontendStack  (frontend cluster/task/service, Lambdas, S3)
```

`XrayIdpStack` depends on `XraySharedStack` because it reads the VPC, the listener's ARN, and the CloudMap namespace - ordinary cross-stack value references, which automatically make CDK deploy `XraySharedStack` first.

`XrayFrontendStack` depends on `XrayIdpStack` for the same reason (it imports idp's security group ID, for the ingress rule that lets its CloudMap side-call reach idp - see [`docs/cloudmap.md`](cloudmap.md)) *and* has an explicit `self.add_dependency(idp_stack)` on top of that. The explicit call is technically redundant - the security-group import already forces the ordering - but it documents the requirement instead of leaving it as an accidental side effect of an unrelated import, the same reasoning behind making the Envoy→app container startup dependency explicit rather than relying on the ALB health check to paper over missing ordering (see [`docs/envoy.md`](envoy.md)).

Deploying (`cdk deploy --all`) and destroying (`cdk destroy --all`) both resolve this graph automatically - the latter in reverse.

## The shared ALB: four real gotchas

The interesting part of this refactor was making one ALB, owned by `XraySharedStack`, work as the entry point for target groups owned by two *other* stacks. All four of the following were caught by an actual `cdk synth` or a real deploy failing, not by reading documentation first - they're the kind of asymmetry that reads as obvious in hindsight but isn't visible from the API's type signatures.

### 1. `add_targets()` doesn't work on an imported listener

The natural-looking code:

```python
listener = elbv2.ApplicationListener.from_application_listener_attributes(
    self, "SharedListener", listener_arn=..., security_group=...,
)
listener.add_targets("IdpTargetGroup", port=80, targets=[service], ...)
```

fails at synth time with `CallAddTargetsConstructedApplication: Can only call addTargets() when using a constructed ApplicationListener; construct a new TargetGroup and use addTargetGroup.` `add_targets()` is a convenience method that constructs *and* registers a target group in one call, and its internal bookkeeping needs the real listener object - not a bare ARN+security-group reference. The type signature (`IApplicationListener`) doesn't reflect this; it's a runtime check.

The fix is exactly what the error says: construct the target group explicitly, then attach it with `add_target_groups()`:

```python
target_group = elbv2.ApplicationTargetGroup(
    self, "IdpTargetGroup", vpc=shared_stack.vpc, port=80, targets=[service],
    health_check=elbv2.HealthCheck(path="/idp/health", healthy_http_codes="200"),
)
listener.add_target_groups(
    "IdpTargetGroupAttachment", target_groups=[target_group],
    priority=10, conditions=[elbv2.ListenerCondition.path_patterns(["/idp", "/idp/*"])],
)
```

### 2. The listener's default action can't move to another stack

Registering a target group behind a priority + path-pattern rule creates an independent `AWS::ElasticLoadBalancingV2::ListenerRule` resource that only needs the listener's ARN - fine to create cross-stack. But the *default action* (what handles requests matching no explicit rule) is a property of the `AWS::ElasticLoadBalancingV2::Listener` resource itself. CloudFormation only lets the stack that owns a resource mutate its properties; an imported reference can't set it.

Since `xray-frontend` used to be the implicit default (no `conditions`, catch-all), this is a genuine capability gap the single-stack version didn't have to deal with. The fix: `XraySharedStack` sets a permanent, static default action once, at listener creation, that never needs touching again -

```python
default_action=elbv2.ListenerAction.fixed_response(404, content_type="text/plain", message_body="Not Found")
```

- and `XrayFrontendStack` registers its own explicit catch-all rule (`path_patterns(["/*"])`, at a low-precedence priority number like 100) instead of relying on being "the" default. `/*` matches every path exactly like a true default would, so nothing about the routing behavior actually changed - only which mechanism implements it.

### 3. Which stack a mutation lands in follows the object, not the calling code

Both `XrayIdpStack` and `XrayFrontendStack` need `shared_stack.alb_security_group` (the ALB's real security group object) to construct the `from_application_listener_attributes(security_group=...)` reference, which CDK uses to automatically pair ingress/egress rules with whatever gets registered as a target. The instinct is to just pass that real object across the stack boundary directly. Doing so is exactly how the SharedStack docstring's warning at the top of this doc becomes a real `DependencyCycle` error: any new resource CDK creates as a side effect of using a real, non-imported construct is anchored to *that construct's own scope* - which is `XraySharedStack`, regardless of which stack's Python code happens to call the method. Since idp's target registration needs idp's own security group ID to pair against, the resulting rule (owned by `XraySharedStack`) ends up importing a value from `XrayIdpStack` - and `XrayIdpStack` already imports the VPC from `XraySharedStack`. Direct cycle, caught by `cdk synth`:

```
DependencyCycle: 'XraySharedStack' depends on 'XrayIdpStack'
(XraySharedStack -> XrayIdpStack/XrayIdpService/SecurityGroup/Resource.GroupId).
Adding this dependency (XrayIdpStack -> XraySharedStack/.../Subnet.Ref)
would create a cyclic reference.
```

The fix, used in three places in this codebase (this ALB security group in both service stacks, and the frontend→idp CloudMap ingress rule in `XrayFrontendStack` - see [`docs/cloudmap.md`](cloudmap.md)): import a **locally-scoped, mutable reference** to the real object instead of passing the real object itself -

```python
alb_security_group = ec2.SecurityGroup.from_security_group_id(
    self, "AlbSecurityGroup", shared_stack.alb_security_group.security_group_id,
)
```

Any new rule CDK creates against *this* object is anchored to the stack that imported it, referencing the real security group purely by ID - a one-directional value import in the same direction the stack already depends, not a new edge back the other way.

### 4. The imported security group's default `allow_all_outbound=True` silently breaks egress

This one wasn't caught by `cdk synth` - it only showed up as a live deploy that never stabilized. After fixing gotcha #3, `XrayIdpStack` created and deployed cleanly, but the ECS service just never went healthy. `aws elbv2 describe-target-health` showed `Target.Timeout` against the idp target - not a connection refusal or an app crash (the container logs showed the app starting and listening on port 3000 within about a second, every time), a network-level timeout, repeating every cycle as ECS kept replacing the "unhealthy" task.

The actual ingress rule (ALB → idp, port 3000) was present and correct - confirmed directly with `aws ec2 describe-security-groups` against the real, live security group, not just the CDK template. What was missing was the *other* half of the pair: an egress rule on the **ALB's** security group allowing it to reach idp in the first place. Checking the ALB's security group's own egress rules directly confirmed it had no blanket "allow all outbound" rule - just CDK's usual explicit-deny ICMP placeholder.

`SecurityGroup.from_security_group_id()` defaults `allow_all_outbound` to `True` on import - meaning it *assumes* the real security group already permits all outbound traffic, and CDK's automatic ALB↔target security-group pairing logic uses that assumption to skip adding an explicit egress rule as "redundant". The assumption was simply wrong for this specific ALB security group (recent CDK versions default ALB security groups to *not* auto-allow-all-outbound, expecting exactly this kind of per-target explicit pairing instead), so the egress rule that idp's target health check actually needed was silently never created.

The fix is one keyword, informed by checking the real resource's real state rather than trusting the SDK default:

```python
alb_security_group = ec2.SecurityGroup.from_security_group_id(
    self, "AlbSecurityGroup", shared_stack.alb_security_group.security_group_id,
    allow_all_outbound=False,
)
```

With `allow_all_outbound=False`, CDK's pairing logic can no longer assume egress is already covered, and adds the real `AWS::EC2::SecurityGroupEgress` resource the ALB needs. Confirmed afterward the same way the bug was found: reading the live security group's rules directly, then watching `aws elbv2 describe-target-health` flip to `healthy`.

## Retiring the old single stack

Because the new stack names (`XraySharedStack`, `XrayIdpStack`, `XrayFrontendStack`) don't match the old `XrayPocStack`, CloudFormation treats them as entirely unrelated stacks - deploying the new topology does not migrate or replace the old one. Since three Lambda function names are hardcoded (`xray-invoker`, `xray-dog-fetcher`, `xray-s3-writer`, both for stable trigger-time discoverability and because they're referenced in this repo's docs and scripts), leaving the old stack running would have caused the new deploy to fail outright on a name collision the moment it tried to create the same function names again.

`cdk destroy` couldn't be used for this, since it only operates on stacks defined in the *current* app - and `XrayPocStack` was no longer defined anywhere once `xray_stack.py` was replaced by the three new files. The old stack had to be torn down directly with `aws cloudformation delete-stack --stack-name XrayPocStack` before the new `cdk deploy --all` could run.
