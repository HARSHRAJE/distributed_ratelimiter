from dataclasses import dataclass
from typing import Any
from urllib.parse import quote
from uuid import UUID

import httpx

from app.config import Settings


class PolicyClientError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        ambiguous: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.ambiguous = ambiguous


@dataclass(frozen=True)
class ServicePolicy:
    id: UUID
    service_key: str
    config_version: int
    global_capacity: int
    global_refill_rate: float
    hard_max_refill_rate: float
    adaptive_enabled: bool


@dataclass(frozen=True)
class EffectiveServicePolicy:
    config_version: int
    global_refill_rate: float


@dataclass(frozen=True)
class AcceptedExecution:
    accepted: bool
    resulting_version: int | None
    resulting_rate: float | None


@dataclass(frozen=True)
class AcceptedRollback:
    accepted: bool
    rollback_version: int | None
    global_refill_rate: float | None


class PolicyClient:
    def __init__(self, settings: Settings) -> None:
        self.base_url = settings.policy_service_url.rstrip("/")
        self.timeout = settings.policy_service_timeout_seconds
        self.headers = {
            "X-Policy-Service-Key": settings.policy_service_api_key
        }

    def get_service(self, service_key: str) -> ServicePolicy:
        data = self._request(
            "GET",
            f"/api/v1/services/by-key/{quote(service_key, safe='')}",
        )
        try:
            return ServicePolicy(
                id=UUID(str(data["id"])),
                service_key=str(data["serviceKey"]),
                config_version=int(data["configVersion"]),
                global_capacity=int(data["globalCapacity"]),
                global_refill_rate=float(data["globalRefillRate"]),
                hard_max_refill_rate=float(data["hardMaxRefillRate"]),
                adaptive_enabled=bool(data["adaptiveEnabled"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PolicyClientError(
                "Policy Service returned an invalid service configuration"
            ) from error

    def set_adaptive_control(
        self,
        service_key: str,
        *,
        expected_version: int,
        enabled: bool,
    ) -> ServicePolicy:
        data = self._request(
            "PUT",
            f"/api/v1/services/by-key/{quote(service_key, safe='')}"
            "/adaptive-control",
            json={
                "expectedConfigVersion": expected_version,
                "enabled": enabled,
            },
        )
        return self._service_from_response(data)

    def set_global_kill_switch(self, *, active: bool) -> None:
        self._request(
            "PUT",
            "/api/v1/services/execution-control",
            json={"active": active},
        )

    def submit(
        self,
        service: ServicePolicy,
        *,
        execution_id: UUID,
        expected_version: int,
        proposed_rate: float,
    ) -> ServicePolicy:
        data = self._request(
            "PUT",
            f"/api/v1/services/{service.id}/adaptive-configuration",
            json={
                "expectedConfigVersion": expected_version,
                "globalCapacity": service.global_capacity,
                "globalRefillRate": proposed_rate,
                "executionId": str(execution_id),
            },
            ambiguous_on_timeout=True,
        )
        return self._service_from_response(data)

    def execution_status(
        self,
        service_id: UUID,
        execution_id: UUID,
    ) -> AcceptedExecution:
        data = self._request(
            "GET",
            f"/api/v1/services/{service_id}/configuration/executions/"
            f"{execution_id}",
            allow_not_found=True,
        )
        if data is None:
            return AcceptedExecution(False, None, None)
        try:
            accepted = bool(data["accepted"])
            version = data.get("resultingVersion")
            rate = data.get("resultingRate")
            return AcceptedExecution(
                accepted,
                int(version) if version is not None else None,
                float(rate) if rate is not None else None,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PolicyClientError(
                "Policy Service returned an invalid execution status"
            ) from error

    def get_effective(self, service_key: str) -> EffectiveServicePolicy:
        data = self._request(
            "GET",
            f"/api/v1/services/by-key/{quote(service_key, safe='')}"
            "/effective-configuration",
        )
        try:
            return EffectiveServicePolicy(
                config_version=int(data["configVersion"]),
                global_refill_rate=float(data["globalRefillRate"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PolicyClientError(
                "Policy Service returned an invalid effective configuration"
            ) from error

    def rollback_service(
        self,
        service: ServicePolicy,
        *,
        rollback_id: UUID,
        expected_active_version: int,
        restored_from_version: int,
    ) -> AcceptedRollback:
        data = self._request(
            "PUT",
            f"/api/v1/services/{service.id}/adaptive-rollback",
            json={
                "expectedActiveVersion": expected_active_version,
                "restoredFromVersion": restored_from_version,
                "rollbackId": str(rollback_id),
            },
            ambiguous_on_timeout=True,
        )
        return self._rollback_from_response(data)

    def rollback_status(
        self,
        service_id: UUID,
        rollback_id: UUID,
    ) -> AcceptedRollback:
        data = self._request(
            "GET",
            f"/api/v1/services/{service_id}/configuration/rollbacks/"
            f"{rollback_id}",
            allow_not_found=True,
        )
        if data is None:
            return AcceptedRollback(False, None, None)
        return self._rollback_from_response(data)

    def _service_from_response(self, data: dict[str, Any]) -> ServicePolicy:
        try:
            return ServicePolicy(
                id=UUID(str(data["id"])),
                service_key=str(data["serviceKey"]),
                config_version=int(data["configVersion"]),
                global_capacity=int(data["globalCapacity"]),
                global_refill_rate=float(data["globalRefillRate"]),
                hard_max_refill_rate=float(data["hardMaxRefillRate"]),
                adaptive_enabled=bool(data["adaptiveEnabled"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PolicyClientError(
                "Policy Service returned an invalid service configuration"
            ) from error

    def _rollback_from_response(
        self,
        data: dict[str, Any] | None,
    ) -> AcceptedRollback:
        if data is None:
            raise PolicyClientError(
                "Policy Service returned an empty rollback response"
            )
        try:
            return AcceptedRollback(
                True,
                int(data["rollbackVersion"]),
                float(data["globalRefillRate"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise PolicyClientError(
                "Policy Service returned an invalid rollback response"
            ) from error

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
        allow_not_found: bool = False,
        ambiguous_on_timeout: bool = False,
    ) -> dict[str, Any] | None:
        if len(self.headers["X-Policy-Service-Key"]) < 32:
            raise PolicyClientError(
                "Policy Service execution credentials are not configured",
                status_code=503,
            )
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                json=json,
                headers=self.headers,
                timeout=self.timeout,
            )
        except httpx.TimeoutException as error:
            raise PolicyClientError(
                "Policy Service request timed out",
                ambiguous=ambiguous_on_timeout,
            ) from error
        except httpx.HTTPError as error:
            raise PolicyClientError(
                "Policy Service is unavailable",
                ambiguous=ambiguous_on_timeout,
            ) from error
        if allow_not_found and response.status_code == 404:
            return None
        if not response.is_success:
            raise PolicyClientError(
                f"Policy Service request failed with status {response.status_code}",
                status_code=response.status_code,
                ambiguous=(
                    ambiguous_on_timeout
                    and response.status_code >= 500
                ),
            )
        if response.status_code == 204:
            return {}
        try:
            payload = response.json()
        except ValueError as error:
            raise PolicyClientError(
                "Policy Service returned invalid JSON",
                ambiguous=ambiguous_on_timeout,
            ) from error
        if not isinstance(payload, dict):
            raise PolicyClientError("Policy Service returned an invalid response")
        return payload
