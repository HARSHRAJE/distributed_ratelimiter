import asyncio
import logging

from app.chaos.experiment_runner import ChaosExperimentRunner
from app.config import Settings
from app.storage.database import create_database_engine, create_session_factory

LOGGER = logging.getLogger(__name__)


async def run_worker() -> None:
    settings = Settings.from_env()
    if not settings.chaos_enabled:
        raise RuntimeError(
            "Set AI_CONTROLLER_CHAOS_ENABLED=true only in an authorized "
            "local test environment"
        )
    engine = create_database_engine(settings)
    runner = ChaosExperimentRunner(
        session_factory=create_session_factory(engine),
        settings=settings,
    )
    LOGGER.warning(
        "Local chaos worker enabled for test environment %s",
        settings.chaos_test_environment_id,
    )
    while True:
        try:
            experiment_id = await runner.run_once()
            if experiment_id is None:
                await asyncio.sleep(settings.chaos_worker_poll_seconds)
            else:
                LOGGER.warning("Chaos experiment processed: %s", experiment_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.exception("Chaos worker iteration failed")
            await asyncio.sleep(settings.chaos_worker_poll_seconds)


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
