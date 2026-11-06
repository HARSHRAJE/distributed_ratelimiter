from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy.engine import Engine

from app.api.health import router as health_router
from app.api.forecast import router as forecast_router
from app.api.telemetry import router as telemetry_router
from app.api.recommendations import router as recommendations_router
from app.api.safety import router as safety_router
from app.api.shadow import router as shadow_router
from app.api.execution import router as execution_router
from app.api.rollback import router as rollback_router
from app.api.circuit_breaker import router as circuit_breaker_router
from app.api.allocation import router as allocation_router
from app.api.route_allocation import router as route_allocation_router
from app.api.sla import router as sla_router
from app.api.benchmarks import router as benchmarks_router
from app.config import Settings
from app.forecasting.metrics import REGISTRY
from app.storage.database import create_database_engine, create_session_factory


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
) -> FastAPI:
    application_settings = settings or Settings.from_env()
    database_engine = engine or create_database_engine(application_settings)
    app = FastAPI(title="AI Controller Telemetry", version="0.1.0")
    app.state.settings = application_settings
    app.state.engine = database_engine
    app.state.session_factory = create_session_factory(database_engine)
    app.include_router(health_router)
    app.include_router(telemetry_router)
    app.include_router(forecast_router)
    app.include_router(recommendations_router)
    app.include_router(safety_router)
    app.include_router(shadow_router)
    app.include_router(execution_router)
    app.include_router(rollback_router)
    app.include_router(circuit_breaker_router)
    app.include_router(allocation_router)
    app.include_router(route_allocation_router)
    app.include_router(sla_router)
    app.include_router(benchmarks_router)

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(
            content=generate_latest(REGISTRY),
            media_type=CONTENT_TYPE_LATEST,
        )

    return app


app = create_app()
