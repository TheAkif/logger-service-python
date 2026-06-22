"""
Locust load test for the Log Ingestor Service (LIS).

Quick start (UI mode):
    locust -f locustfile.py --host http://localhost:8000

Headless with the default ramp shape:
    INGEST_TOKEN=dev-secret locust -f locustfile.py \
        --host http://localhost:8000 \
        --users 50 --spawn-rate 5 --run-time 60s --headless

High-volume stress run (uses DHLikeLogShape):
    INGEST_TOKEN=dev-secret PER_USER_LOGS_PER_SEC=10 \
        locust -f locustfile.py --host http://localhost:8000 --headless

Environment variables:
    INGEST_TOKEN        Bearer token (default: dev-secret)
    LOG_SOURCE          source field value (default: order-service)
    LOG_ENV             environment field (default: dev)
    PER_USER_LOGS_PER_SEC   throughput per Locust user (default: 10)
    BATCH_SIZE          events per batch request (default: 20)
"""

import math
import os
import random
import time
import uuid

from locust import HttpUser, LoadTestShape, between, constant_throughput, task

# ── Config ────────────────────────────────────────────────────────────────────

INGEST_TOKEN = os.getenv("INGEST_TOKEN", "dev-secret")
LOG_SOURCE = os.getenv("LOG_SOURCE", "order-service")
LOG_ENV = os.getenv("LOG_ENV", "dev")
PER_USER_LOGS_PER_SEC = float(os.getenv("PER_USER_LOGS_PER_SEC", "10"))
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "20"))

_AUTH_HEADERS = {"Authorization": f"Bearer {INGEST_TOKEN}"}

# ── Data pools ────────────────────────────────────────────────────────────────

_TENANTS = ["tenant-a", "tenant-b", "tenant-c", "tenant-d"]
_BUSINESS_ROUTES = ["/order", "/users", "/search"]
_ROUTE_WEIGHTS = [3, 2, 5]
_PODS = [f"pod-{i}" for i in range(1, 51)]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _trace() -> dict:
    return {
        "traceId": uuid.uuid4().hex,
        "correlationId": f"req-{uuid.uuid4().hex[:12]}",
    }


def _make_access_log() -> dict:
    route = random.choices(_BUSINESS_ROUTES, weights=_ROUTE_WEIGHTS, k=1)[0]
    method = "POST" if route == "/order" and random.random() < 0.35 else "GET"

    r = random.random()
    if r < 0.92:
        status, level = 200, "info"
    elif r < 0.98:
        status = random.choice([400, 401, 403, 404, 409, 422])
        level = "warn"
    else:
        status = random.choice([500, 502, 503])
        level = "error"

    return {
        "occurredAt": _now(),
        "tenantId": random.choice(_TENANTS),
        "source": LOG_SOURCE,
        "environment": LOG_ENV,
        "level": level,
        "type": "access",
        "message": f"{method} {route}",
        **_trace(),
        "method": method,
        "path": route,
        "statusCode": status,
        "durationMs": random.randint(5, 1200),
        "properties": {
            "node": random.choice(_PODS),
        },
    }


_APP_MESSAGES = [
    "User login successful",
    "Login failed: invalid password",
    "Session expired",
    "Database connection pool exhausted",
    "Cache miss - falling back to DB",
    "Background job completed",
    "Config reloaded",
    "Rate limit hit for tenant",
    "Unhandled exception in request handler",
    "Service dependency timeout",
]


def _make_app_log() -> dict:
    level = random.choices(
        ["debug", "info", "warn", "error", "fatal"],
        weights=[5, 50, 25, 15, 5],
        k=1,
    )[0]
    payload: dict = {
        "occurredAt": _now(),
        "tenantId": random.choice(_TENANTS),
        "source": LOG_SOURCE,
        "environment": LOG_ENV,
        "level": level,
        "type": "app",
        "message": random.choice(_APP_MESSAGES),
        **_trace(),
        "userId": f"user-{random.randint(1, 9999)}",
        "properties": {"node": random.choice(_PODS)},
    }
    if level in ("error", "fatal"):
        payload["exception"] = {
            "name": "RuntimeError",
            "message": "unexpected internal failure",
            "stack": "...",
        }
    return payload


def _make_audit_log() -> dict:
    actions = ["user.login", "user.logout", "record.create", "record.delete", "role.assign"]
    return {
        "occurredAt": _now(),
        "tenantId": random.choice(_TENANTS),
        "source": LOG_SOURCE,
        "environment": LOG_ENV,
        "level": "info",
        "type": "audit",
        "message": f"audit: {random.choice(actions)}",
        **_trace(),
        "userId": f"user-{random.randint(1, 9999)}",
        "properties": {"action": random.choice(actions)},
    }


def _random_event() -> dict:
    return random.choices(
        [_make_access_log, _make_app_log, _make_audit_log],
        weights=[60, 30, 10],
        k=1,
    )[0]()


# ── User classes ──────────────────────────────────────────────────────────────


class LogProducerUser(HttpUser):
    """
    Primary load profile - simulates a service shipping single log events
    at a controlled rate (PER_USER_LOGS_PER_SEC per Locust user).

    Use this class with DHLikeLogShape for the staged ramp.
    """

    wait_time = constant_throughput(PER_USER_LOGS_PER_SEC)

    @task(7)
    def ingest_single(self):
        self.client.post(
            "/v1/logs",
            json=_random_event(),
            headers=_AUTH_HEADERS,
            name="POST /v1/logs",
        )

    @task(3)
    def ingest_batch(self):
        events = [_random_event() for _ in range(BATCH_SIZE)]
        with self.client.post(
            "/v1/logs/batch",
            json=events,
            headers=_AUTH_HEADERS,
            name="POST /v1/logs/batch",
            catch_response=True,
        ) as resp:
            if resp.status_code == 202:
                resp.success()
            elif resp.status_code == 503:
                resp.failure("queue full")
            else:
                resp.failure(f"unexpected {resp.status_code}")


class SteadyMixUser(HttpUser):
    """
    Lighter profile for quick local runs (UI mode default).
    Mixes single events, batches, health probes, and batcher stats.
    Run this with a low user count (10–30) to explore behaviour without
    triggering back-pressure.
    """

    wait_time = between(0.05, 0.3)

    @task(5)
    def ingest_single(self):
        self.client.post(
            "/v1/logs",
            json=_random_event(),
            headers=_AUTH_HEADERS,
            name="POST /v1/logs",
        )

    @task(3)
    def ingest_batch(self):
        size = random.randint(5, 50)
        with self.client.post(
            "/v1/logs/batch",
            json=[_random_event() for _ in range(size)],
            headers=_AUTH_HEADERS,
            name="POST /v1/logs/batch",
            catch_response=True,
        ) as resp:
            if resp.status_code in (202, 503):
                resp.success()
            else:
                resp.failure(f"unexpected {resp.status_code}")

    @task(1)
    def health(self):
        self.client.get("/health", name="GET /health")

    @task(1)
    def batcher_stats(self):
        self.client.get("/internal/batcher", name="GET /internal/batcher")


# ── Load shape ────────────────────────────────────────────────────────────────


class DHLikeLogShape(LoadTestShape):
    """
    Staged ramp that simulates a realistic spike-to-burst pattern.

    Stage          | Duration | Target logs/sec | Spawn rate
    ─────────────────────────────────────────────────────────
    Warm-up        |  5 min   |  2 000          |  500
    Sustained load |  2 min   | 10 000          | 1500
    Burst          |  1 min   | 30 000          | 3000
    Cool-down      |  1 min   |  2 000          | 2000

    Activate by NOT specifying --users; Locust uses this shape automatically
    when it is defined. Remove or rename the class to use manual user counts.

    User count = ceil(target_lps / PER_USER_LOGS_PER_SEC)
    """

    stages = [
        {"duration_s": 5 * 60, "target_lps": 2_000, "spawn_rate": 500},
        {"duration_s": 2 * 60, "target_lps": 10_000, "spawn_rate": 1_500},
        {"duration_s": 60,     "target_lps": 30_000, "spawn_rate": 3_000},
        {"duration_s": 60,     "target_lps": 2_000,  "spawn_rate": 2_000},
    ]

    def tick(self):
        run_time = self.get_run_time()
        elapsed = 0
        for stage in self.stages:
            elapsed += stage["duration_s"]
            if run_time < elapsed:
                users = math.ceil(stage["target_lps"] / PER_USER_LOGS_PER_SEC)
                return (users, stage["spawn_rate"])
        return None
