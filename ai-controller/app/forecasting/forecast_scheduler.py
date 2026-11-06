import asyncio
import logging
import os
import signal
import time

from prometheus_client import start_http_server
from sqlalchemy.engine import Engine

from app.circuit_breaker.health_evaluator import HealthEvaluator
from app.config import Settings
from app.forecasting.metrics import REGISTRY
from app.storage.database import create_database_engine, create_session_factory
from app.forecasting.forecast_service import scheduled_forecast_cycle

logger = logging.getLogger("ai_controller.forecast_worker")
FORECAST_WORKER_ADVISORY_LOCK_ID = 8_194_330_175_010_152


def try_acquire_worker_lock(engine: Engine):
    connection = engine.raw_connection()
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s)",
            (FORECAST_WORKER_ADVISORY_LOCK_ID,),
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


async def run_worker(settings: Settings, engine: Engine) -> None:
    lock_connection = None
    while lock_connection is None:
        try:
            lock_connection = await asyncio.to_thread(
                try_acquire_worker_lock,
                engine,
            )
        except Exception as error:
            logger.error(
                "Could not acquire forecast worker lock error_type=%s",
                type(error).__name__,
            )
        if lock_connection is None:
            await asyncio.sleep(settings.collection_interval_seconds)

    logger.info("Forecast worker acquired the PostgreSQL advisory lock")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for stop_signal in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(stop_signal, stop_event.set)
        except NotImplementedError:
            pass

    session_factory = create_session_factory(engine)
    last_evaluation = 0.0
    try:
        while not stop_event.is_set():
            evaluate_accuracy = time.monotonic() - last_evaluation >= 300
            await asyncio.to_thread(
                scheduled_forecast_cycle,
                settings,
                session_factory,
                evaluate_accuracy=evaluate_accuracy,
            )
            await asyncio.to_thread(
                update_breaker_health,
                settings,
                session_factory,
            )
            if evaluate_accuracy:
                last_evaluation = time.monotonic()
            delay = settings.collection_interval_seconds - (
                time.time() % settings.collection_interval_seconds
            )
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass
    finally:
        cursor = lock_connection.cursor()
        try:
            cursor.execute(
                "SELECT pg_advisory_unlock(%s)",
                (FORECAST_WORKER_ADVISORY_LOCK_ID,),
            )
        finally:
            cursor.close()
        lock_connection.close()
        logger.info("Forecast worker released the advisory lock")


def update_breaker_health(settings: Settings, session_factory) -> None:
    for service_key in settings.service_keys:
        with session_factory() as session:
            HealthEvaluator(settings).evaluate(
                service_key,
                session=session,
            )


def main() -> None:
    logging.basicConfig(
        level=getattr(
            logging,
            os.getenv("LOG_LEVEL", "INFO").upper(),
            logging.INFO,
        ),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    settings = Settings.from_env()
    engine = create_database_engine(settings)
    metrics_server, metrics_thread = start_http_server(
        8001,
        addr="0.0.0.0",
        registry=REGISTRY,
    )
    try:
        asyncio.run(run_worker(settings, engine))
    finally:
        metrics_server.shutdown()
        metrics_thread.join()
        engine.dispose()


if __name__ == "__main__":
    main()
