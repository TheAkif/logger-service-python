import os
import time
import uuid
import random
import math
from locust import HttpUser, task, constant_throughput, LoadTestShape


def iso_utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


PER_USER_LOGS_PER_SEC = float(os.getenv("PER_USER_LOGS_PER_SEC", "10"))
INGEST_TOKEN = os.getenv("INGEST_TOKEN", "dev-token")
LOG_SOURCE = os.getenv("LOG_SOURCE", "order-service")
LOG_ENV = os.getenv("LOG_ENV", "dev")
# ----------------------------------------


TENANTS = ["tenant-a", "tenant-b", "tenant-c", "tenant-d"]
BUSINESS_ROUTES = ["/order", "/users", "/search"]
ROUTE_WEIGHTS = [3, 2, 5]


class LogProducerUser(HttpUser):
    """
    Sends access-style logs to:
      POST /v1/logs
    pretending they were produced by one service (order-service) handling 3 routes,
    used by 4 tenants.
    """
    wait_time = constant_throughput(PER_USER_LOGS_PER_SEC)

    def on_start(self):
        self.headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {INGEST_TOKEN}",
        }

    def _pick_route(self) -> str:
        return random.choices(BUSINESS_ROUTES, weights=ROUTE_WEIGHTS, k=1)[0]

    def _make_access_log(self, route: str) -> dict:
        tenant = random.choice(TENANTS)

        method = "POST" if route == "/order" and random.random() < 0.35 else "GET"

        r = random.random()
        if r < 0.92:
            status = 200
            level = "info"
        elif r < 0.98:
            status = random.choice([400, 401, 403, 404, 409, 422])
            level = "warn"
        else:
            status = random.choice([500, 502, 503])
            level = "error"

        duration_ms = random.randint(5, 1200)

        return {
            "occurredAt": iso_utc_now(),
            "tenantId": tenant,
            "source": LOG_SOURCE,
            "environment": LOG_ENV,
            "level": level,
            "type": "access",
            "message": f"{method} {route}",
            "traceId": uuid.uuid4().hex,
            "correlationId": f"req-{uuid.uuid4().hex[:12]}",
            "method": method,
            "path": route,
            "statusCode": status,
            "durationMs": duration_ms,
            "properties": {
                "service": LOG_SOURCE,
                "endpoint": route,
                "node": f"pod-{random.randint(1, 50)}",
            },
        }

    @task
    def ingest_log(self):
        route = self._pick_route()
        payload = self._make_access_log(route)

        self.client.post(
            "/v1/logs",
            json=payload,
            headers=self.headers,
            name="POST /v1/logs (access)",
        )


class DHLikeLogShape(LoadTestShape):
    """
    Stage profile by *logs/sec*:
      1) 2k logs/sec for 10 min
      2) 10k logs/sec for 5 min
      3) 30k logs/sec for 60 sec (burst)
      4) 2k logs/sec for 2 min (cooldown)
      then stop

    We convert target logs/sec -> users using PER_USER_LOGS_PER_SEC.
    """
    stages = [
        {"duration_s": 5 * 60, "target_lps": 2000, "spawn_rate": 500},
        {"duration_s": 2 * 60,  "target_lps": 10000, "spawn_rate": 1500},
        {"duration_s": 60,      "target_lps": 30000, "spawn_rate": 3000},
        {"duration_s": 60,  "target_lps": 2000, "spawn_rate": 2000},
    ]

    def tick(self):
        run_time = self.get_run_time()

        elapsed = 0
        for s in self.stages:
            elapsed += s["duration_s"]
            if run_time < elapsed:
                users = math.ceil(s["target_lps"] / 5)
                return (users, s["spawn_rate"])

        return None
