import httpx
import pytest

from app.telemetry.prometheus_client import PrometheusClient


@pytest.mark.asyncio
async def test_query_returns_prometheus_vector() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/query"
        assert request.url.params["query"] == "up"
        return httpx.Response(
            200,
            json={
                "status": "success",
                "data": {"result": [{"value": [1, "1"]}]},
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        result = await PrometheusClient(
            "http://prometheus:9090/",
            client=client,
        ).query("up")

    assert result == [{"value": [1, "1"]}]


@pytest.mark.asyncio
async def test_query_raises_for_prometheus_api_error() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"status": "error", "errorType": "bad_data"},
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler)
    ) as client:
        with pytest.raises(RuntimeError, match="non-success status"):
            await PrometheusClient("http://prometheus", client).query("bad")
