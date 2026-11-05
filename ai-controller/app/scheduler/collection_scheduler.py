import asyncio
import logging
import os
import signal
import time
from datetime import datetime, timezone

import httpx
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError

from app.config import Settings
from app.storage.database import create_database_engine, create_session_factory
from app.storage.repositories import TelemetryRepository
from app.telemetry.aggregator import TelemetryAggregator
from app.telemetry.collector import TelemetryCollector
from app.telemetry.prometheus_client import PrometheusClient

logger = logging.getLogger("ai_controller.collector")
WORKER_ADVISORY_LOCK_ID = 8_194_330_175_010_151


def collection_window_start(now: datetime, interval_seconds: int) -> datetime:
    epoch = int(now.timestamp())
    aligned = epoch - epoch % interval_seconds
    return datetime.fromtimestamp(aligned, tz=timezone.utc)


def try_acquire_worker_lock(engine: Engine):
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (WORKER_ADVISORY_LOCK_ID,),
        )
        acquired = bool(cursor.fetchone()[0])
        cursor.close()
        if not acquired:
            connection.close()
            return None
        return connection
    except Exception:
        connection.close()
        raise


async def collect_cycle(
    settings: Settings,
    engine: Engine,
    collector: TelemetryCollector,
    aggregator: TelemetryAggregator,
    *,
    now: datetime | None = None,
) -> None:
    collected_at = now or datetime.now(timezone.utc)
    window_start = collection_window_start(
        collected_at,
        settings.collection_interval_seconds,
    )
    session_factory = create_session_factory(engine)

    for service_key in settings.service_keys:
        attempted_at = datetime.now(timezone.utc)
        try:
            sample = await collector.collect(service_key, now=collected_at)
        except Exception as error:
            _record_failure(
                session_factory,
                service_key,
                attempted_at,
                error,
            )
            continue

        retry_delay = 1
        while True:
            try:
                with session_factory() as session:
                    repository = TelemetryRepository(session)
                    repository.save_sample(sample)
                    repository.aggregate_window(
                        service_key,
                        window_start=window_start,
                        window_seconds=settings.aggregation_window_seconds,
                        collection_interval_seconds=(
                            settings.collection_interval_seconds
                        ),
                        aggregator=aggregator,
                    )
                    repository.record_collection_success(
                        service_key,
                        attempted_at=attempted_at,
                        quality=sample.data_quality,
                    )
                logger.info(
                    "Collected telemetry for service=%s quality=%s",
                    service_key,
                    sample.data_quality,
                )
                break
            except OperationalError as error:
                logger.error(
                    "PostgreSQL unavailable while persisting service=%s; "
                    "retrying same sample error_type=%s delay_seconds=%d",
                    service_key,
                    type(error).__name__,
                    retry_delay,
                )
                _record_failure(
                    session_factory,
                    service_key,
                    attempted_at,
                    error,
                )
                await asyncio.sleep(retry_delay)
                retry_delay = min(retry_delay * 2, 15)
            except Exception as error:
                _record_failure(
                    session_factory,
                    service_key,
                    attempted_at,
                    error,
                )
                break


def _record_failure(
    session_factory,
    service_key: str,
    attempted_at: datetime,
    error: Exception,
) -> None:
    logger.error(
        "Telemetry collection failed for service=%s error_type=%s",
        service_key,
        type(error).__name__,
    )
    try:
        with session_factory() as session:
            TelemetryRepository(session).record_collection_failure(
                service_key,
                attempted_at=attempted_at,
                error_type=type(error).__name__,
            )
    except Exception as status_error:
        logger.error(
            "Could not persist collection failure for service=%s "
            "error_type=%s",
            service_key,
            type(status_error).__name__,
        )


async def run_worker(settings: Settings, engine: Engine) -> None:
    logger.info(
        "Telemetry worker configured interval_seconds=%d services=%d",
        settings.collection_interval_seconds,
        len(settings.service_keys),
    )

    lock_connection = None
    while lock_connection is None:
        try:
            lock_connection = await asyncio.to_thread(
                try_acquire_worker_lock,
                engine,
            )
        except Exception as error:
            logger.error(
                "Could not acquire telemetry worker lock error_type=%s",
                type(error).__name__,
            )
        if lock_connection is None:
            await asyncio.sleep(settings.collection_interval_seconds)

    logger.info("Telemetry worker acquired the PostgreSQL advisory lock")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(stop_signal, stop_event.set)
        except NotImplementedError:
            pass

    timeout = httpx.Timeout(settings.prometheus_timeout_seconds)
    async with httpx.AsyncClient(timeout=timeout) as http_client:
        prometheus = PrometheusClient(
            settings.prometheus_url,
            client=http_client,
        )
        collector = TelemetryCollector(
            prometheus,
            stale_after_seconds=settings.stale_after_seconds,
            collection_interval_seconds=(
                settings.collection_interval_seconds
            ),
        )
        aggregator = TelemetryAggregator()

        try:
            while not stop_event.is_set():
                await collect_cycle(
                    settings,
                    engine,
                    collector,
                    aggregator,
                )
                delay = settings.collection_interval_seconds - (
                    time.time() % settings.collection_interval_seconds
                )
                try:
                    await asyncio.wait_for(stop_event.wait(), timeout=delay)
                except TimeoutError:
                    pass
        finally:
            lock_connection.close()
            logger.info("Telemetry worker released the advisory lock")


def main() -> None:
    logging.basicConfig(
        level=os_level(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    engine = create_database_engine(settings)
    try:
        asyncio.run(run_worker(settings, engine))
    finally:
        engine.dispose()


def os_level() -> int:
    return getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)


if __name__ == "__main__":
    main()
