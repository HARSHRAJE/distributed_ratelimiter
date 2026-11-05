from typing import Any

import httpx


class PrometheusClient:
    def __init__(
        self,
        base_url: str,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = client

    async def query(self, promql: str) -> list[dict[str, Any]]:
        if self._client is not None:
            return await self._execute_query(self._client, promql)

        async with httpx.AsyncClient(timeout=5.0) as client:
            return await self._execute_query(client, promql)

    async def _execute_query(
        self,
        client: httpx.AsyncClient,
        promql: str,
    ) -> list[dict[str, Any]]:
        response = await client.get(
            f"{self.base_url}/api/v1/query",
            params={"query": promql},
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("status") != "success":
            raise RuntimeError("Prometheus query returned a non-success status")

        data = payload.get("data")
        result = data.get("result") if isinstance(data, dict) else None
        if not isinstance(result, list):
            raise RuntimeError("Prometheus query returned an invalid result")
        return result
