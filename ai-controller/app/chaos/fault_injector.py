import asyncio
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import Settings


class ChaosSafetyError(RuntimeError):
    pass


@dataclass(frozen=True)
class FaultObservation:
    fault_probes: list[dict]
    recovery_probe: dict | None
    recovery_time_ms: int | None
    redis_restart_confirmed: bool
    compose_events: list[str]


class FaultInjector:
    _SUPPORTED_SCENARIO = "CH-01"
    _REDIS_SERVICE = "redis"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    async def inject_redis_unavailable(
        self,
        *,
        duration_seconds: int,
    ) -> FaultObservation:
        self._validate_local_environment()
        await self._validate_compose_service()
        await self._preflight_probe()
        events: list[str] = []
        fault_probes: list[dict] = []
        recovery_probe = None
        recovery_time_ms = None
        stopped = False
        stop_attempted = False
        failure: Exception | None = None
        try:
            stop_attempted = True
            await self._compose("stop", self._REDIS_SERVICE)
            stopped = True
            events.append("Stopped the local Compose redis service")
            deadline = time.monotonic() + duration_seconds
            while time.monotonic() < deadline:
                fault_probes.append(await self._probe())
                await asyncio.sleep(min(1, max(0, deadline - time.monotonic())))
        except Exception as error:
            failure = error
        finally:
            if stop_attempted:
                try:
                    restart_started = time.monotonic()
                    await self._compose("start", self._REDIS_SERVICE)
                    events.append("Started the local Compose redis service")
                    recovery_probe, recovery_time_ms = await self._wait_for_recovery(
                        restart_started,
                    )
                except Exception as cleanup_error:
                    if failure is not None:
                        raise ChaosSafetyError(
                            "Redis stop failed and restart could not be verified "
                            f"({type(cleanup_error).__name__})"
                        ) from cleanup_error
                    raise
        if failure is not None:
            raise failure
        if not stopped:
            raise ChaosSafetyError("Redis was not stopped; no fault was injected")
        return FaultObservation(
            fault_probes=fault_probes,
            recovery_probe=recovery_probe,
            recovery_time_ms=recovery_time_ms,
            redis_restart_confirmed=recovery_probe is not None,
            compose_events=events,
        )

    def _validate_local_environment(self) -> None:
        if not self.settings.chaos_enabled:
            raise ChaosSafetyError("Chaos testing is disabled")
        if not self.settings.chaos_test_environment_id:
            raise ChaosSafetyError("Chaos test environment is not configured")
        if not self.settings.chaos_compose_project_directory:
            raise ChaosSafetyError("Local Compose project directory is not configured")
        try:
            project_directory = Path(
                self.settings.chaos_compose_project_directory
            ).resolve(strict=True)
            configured_compose_file = Path(self.settings.chaos_compose_file)
            compose_file = (
                configured_compose_file
                if configured_compose_file.is_absolute()
                else project_directory / configured_compose_file
            ).resolve(strict=True)
            compose_file.relative_to(project_directory)
        except (OSError, ValueError) as error:
            raise ChaosSafetyError(
                "Chaos Compose file must exist inside the configured local "
                "test project directory"
            ) from error
        if not compose_file.is_file():
            raise ChaosSafetyError("Configured Compose file is not a file")
        environment_id = self.settings.chaos_test_environment_id
        if re.fullmatch(r"[A-Za-z0-9._-]{1,100}", environment_id) is None:
            raise ChaosSafetyError("Chaos test environment identifier is invalid")
        self._validate_probe_url()

    def _validate_probe_url(self) -> None:
        parsed = urlparse(self.settings.chaos_probe_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ChaosSafetyError("Chaos protected-route probe URL is invalid")
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError as error:
            raise ChaosSafetyError("Chaos probe URL has an invalid port") from error
        if f"{parsed.hostname.lower()}:{port}" not in {
            host.lower() for host in self.settings.chaos_allowed_hosts
        }:
            raise ChaosSafetyError(
                "Chaos probe host and port are not on the local allowlist"
            )
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ChaosSafetyError(
                "Chaos probe URL must not contain credentials or query values"
            )

    async def _validate_compose_service(self) -> None:
        context = await self._docker("context", "show")
        if context.strip() not in {"default", "desktop-linux"}:
            raise ChaosSafetyError(
                "Chaos experiments only support a local Docker context"
            )
        if os.environ.get("DOCKER_HOST"):
            raise ChaosSafetyError(
                "Chaos experiments do not allow a DOCKER_HOST override"
            )
        endpoint_json = await self._docker(
            "context",
            "inspect",
            "--format",
            "{{json .Endpoints.docker.Host}}",
        )
        try:
            endpoint = json.loads(endpoint_json)
        except json.JSONDecodeError as error:
            raise ChaosSafetyError(
                "Docker context returned an invalid daemon endpoint"
            ) from error
        if not isinstance(endpoint, str) or not endpoint.lower().startswith(
            ("npipe:////./pipe/", "unix:///")
        ):
            raise ChaosSafetyError(
                "Chaos experiments require a local named-pipe or Unix-socket "
                "Docker endpoint"
            )
        config_json = await self._compose("config", "--format", "json")
        try:
            compose_config = json.loads(config_json)
        except json.JSONDecodeError as error:
            raise ChaosSafetyError(
                "Configured Compose project returned invalid configuration"
            ) from error
        redis = compose_config.get("services", {}).get(self._REDIS_SERVICE)
        if not isinstance(redis, dict):
            raise ChaosSafetyError(
                "Configured Compose project does not define the redis service"
            )
        if (
            redis.get("image") != "redis:7.4"
            or "build" in redis
            or redis.get("privileged", False)
            or redis.get("network_mode") == "host"
        ):
            raise ChaosSafetyError(
                "Compose redis service does not match the approved local "
                "Redis test configuration"
            )

    async def _preflight_probe(self) -> None:
        response = await self._probe()
        if response["status_code"] not in {200, 201, 202, 204, 429}:
            raise ChaosSafetyError(
                "Protected route must be healthy before injecting Redis outage"
            )

    async def _probe(self) -> dict:
        headers = {}
        if self.settings.chaos_probe_authorization:
            headers["Authorization"] = (
                self.settings.chaos_probe_authorization
            )
        started = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(
                    self.settings.chaos_probe_url,
                    headers=headers,
                )
        except httpx.HTTPError as error:
            return {
                "status_code": None,
                "latency_ms": round((time.monotonic() - started) * 1000, 3),
                "error_type": type(error).__name__,
            }
        return {
            "status_code": response.status_code,
            "latency_ms": round((time.monotonic() - started) * 1000, 3),
        }

    async def _wait_for_recovery(
        self,
        restart_started: float,
    ) -> tuple[dict | None, int | None]:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            redis_ready = False
            try:
                output = await self._compose(
                    "exec",
                    "-T",
                    self._REDIS_SERVICE,
                    "redis-cli",
                    "ping",
                    timeout_seconds=3,
                )
                redis_ready = output.strip() == "PONG"
            except ChaosSafetyError:
                await asyncio.sleep(1)
                continue
            if redis_ready:
                probe = await self._probe()
                if probe["status_code"] in {200, 201, 202, 204, 429}:
                    return (
                        probe,
                        int((time.monotonic() - restart_started) * 1000),
                    )
            await asyncio.sleep(1)
        return None, None

    async def _compose(
        self,
        *arguments: str,
        timeout_seconds: int = 20,
    ) -> str:
        return await self._run(
            [
                "docker",
                "compose",
                "--project-directory",
                str(Path(self.settings.chaos_compose_project_directory).resolve()),
                "-f",
                str(
                    (
                        Path(self.settings.chaos_compose_project_directory)
                        / self.settings.chaos_compose_file
                    ).resolve()
                ),
                *arguments,
            ],
            timeout_seconds=timeout_seconds,
        )

    @staticmethod
    async def _docker(*arguments: str) -> str:
        return await FaultInjector._run(
            ["docker", *arguments],
            timeout_seconds=5,
        )

    @staticmethod
    async def _run(
        command: list[str],
        *,
        timeout_seconds: int,
    ) -> str:
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except OSError as error:
            raise ChaosSafetyError(
                "Docker CLI is not available to the local chaos worker"
            ) from error
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds,
            )
        except TimeoutError as error:
            process.kill()
            await process.wait()
            raise ChaosSafetyError("Docker Compose command timed out") from error
        if process.returncode:
            raise ChaosSafetyError(
                "Local Docker Compose command failed "
                f"(exit code {process.returncode})"
            )
        return stdout.decode(errors="replace")
