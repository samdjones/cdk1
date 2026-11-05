"""E2E app tests: real x-ray containers + Lambdas inside Floci.

Run via ``x-ray/ci/e2e_test.sh``. ``E2E_ALB_URL`` is the host-published ALB
listener. /fetch-dog needs internet access (the dog-fetcher Lambda calls
dog.ceo and downloads the image).
"""

import json
import os
import time
import urllib.error
import urllib.request

import boto3
import pytest

ALB_URL = os.environ.get("E2E_ALB_URL", "")


def get(path, timeout=90):
    with urllib.request.urlopen(f"{ALB_URL}{path}", timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


@pytest.fixture(scope="module", autouse=True)
def alb_ready():
    """Wait until the ALB forwards to both backends (targets registered)."""
    if not ALB_URL.startswith("http://localhost"):
        pytest.exit(
            f"E2E_ALB_URL must point at the local Floci ALB (got {ALB_URL!r}). "
            "Run x-ray/ci/e2e_test.sh instead.",
            returncode=2,
        )
    deadline = time.time() + 120
    pending = {"/idp/health", "/health"}
    while pending and time.time() < deadline:
        for path in list(pending):
            try:
                if get(path, timeout=5)[0] == 200:
                    pending.discard(path)
            except (urllib.error.URLError, OSError, ValueError):
                pass
        time.sleep(2)
    assert not pending, f"ALB never routed to: {sorted(pending)}"


def test_idp_is_routed_by_path():
    status, body = get("/idp/health")
    assert status == 200
    assert body == {"status": "ok", "service": "xray-idp"}


def test_default_route_reaches_frontend():
    assert get("/health") == (200, {"status": "ok"})


def test_fetch_dog_runs_the_whole_chain_and_stores_in_s3():
    # ALB -> Envoy -> frontend -> dog-fetcher Lambda -> s3-writer Lambda -> S3
    status, body = get("/fetch-dog")
    assert status == 200
    assert body["imageUrl"].startswith("https://images.dog.ceo/")
    keys = body["s3Result"]

    s3 = boto3.client("s3")
    image = s3.head_object(Bucket=keys["bucket"], Key=keys["imageKey"])
    assert image["ContentLength"] > 0
    metadata = json.loads(
        s3.get_object(Bucket=keys["bucket"], Key=keys["metadataKey"])["Body"].read()
    )
    assert metadata["imageUrl"] == body["imageUrl"]
