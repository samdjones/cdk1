"""E2E app tests: real alb app containers behind the ALB, all inside Floci.

Run via ``alb/ci/e2e_test.sh`` (builds the images, starts Floci with real
ECS, deploys, then calls pytest). ``E2E_ALB_URL`` is the host-published
ALB listener.
"""

import json
import os
import time
import urllib.error
import urllib.request

import pytest

ALB_URL = os.environ.get("E2E_ALB_URL", "")


def get(path, timeout=5):
    with urllib.request.urlopen(f"{ALB_URL}{path}", timeout=timeout) as resp:
        return resp.status, json.loads(resp.read())


@pytest.fixture(scope="module", autouse=True)
def alb_ready():
    """Wait until the ALB forwards to all three backends (targets registered)."""
    if not ALB_URL.startswith("http://localhost"):
        pytest.exit(
            f"E2E_ALB_URL must point at the local Floci ALB (got {ALB_URL!r}). "
            "Run alb/ci/e2e_test.sh instead.",
            returncode=2,
        )
    deadline = time.time() + 60
    pending = {"/main/x": "main", "/auth/x": "auth", "/x": "default"}
    while pending and time.time() < deadline:
        for path, service in list(pending.items()):
            try:
                if get(path)[1].get("service") == service:
                    del pending[path]
            except (urllib.error.URLError, OSError, ValueError):
                pass
        time.sleep(1)
    assert not pending, f"ALB never routed to: {sorted(pending.values())}"


@pytest.mark.parametrize(
    "path,service",
    [
        ("/main/foo", "main"),
        ("/main/a/b", "main"),
        ("/auth/bar", "auth"),
        ("/anything", "default"),
        ("/", "default"),
    ],
)
def test_path_routes_to_the_right_backend(path, service):
    status, body = get(path)
    assert status == 200
    assert body == {"service": service, "path": path}


def test_unmatched_prefix_falls_through_to_default():
    # Only "/main/*" and "/auth/*" have rules; "/mainframe" must not match.
    _, body = get("/mainframe")
    assert body["service"] == "default"
