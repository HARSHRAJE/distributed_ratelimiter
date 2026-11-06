import asyncio
import logging

from app.benchmarking.benchmark_runner import BenchmarkRunner
from app.config import Settings
from app.storage.database import create_database_engine, create_session_factory

LOGGER = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = Settings.from_env()
    engine = create_database_engine(settings)
    runner = BenchmarkRunner(
        session_factory=create_session_factory(engine),
        settings=settings,
    )
    LOGGER.info("Benchmark worker started")
    while True:
        try:
            run_id = await runner.run_once()
            if run_id is None:
                await asyncio.sleep(settings.benchmark_worker_poll_seconds)
            else:
                LOGGER.info("Benchmark run processed: %s", run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Benchmark worker iteration failed")
            await asyncio.sleep(settings.benchmark_worker_poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
