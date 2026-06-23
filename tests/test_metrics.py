from httpx import AsyncClient


async def test_metrics_endpoint_returns_200(async_client: AsyncClient):
    resp = await async_client.get("/metrics")
    assert resp.status_code == 200
    assert "text/plain" in resp.headers["content-type"]


async def test_metrics_contains_lis_counters(async_client: AsyncClient, auth_headers: dict):
    # Trigger an ingest so the counters have non-zero values
    await async_client.post(
        "/v1/logs",
        json={
            "tenantId": "metrics-tenant",
            "source": "test",
            "environment": "dev",
            "level": "info",
            "type": "app",
            "message": "metrics test event",
        },
        headers=auth_headers,
    )

    resp = await async_client.get("/metrics")
    assert resp.status_code == 200
    body = resp.text

    for metric in (
        "lis_events_enqueued_total",
        "lis_events_flushed_total",
        "lis_events_dropped_total",
        "lis_flush_errors_total",
        "lis_queue_depth",
        "lis_flush_duration_seconds",
    ):
        assert metric in body, f"missing metric: {metric}"
