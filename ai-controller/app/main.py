from fastapi import FastAPI
from sqlalchemy.engine import Engine

from app.api.health import router as health_router
from app.api.telemetry import router as telemetry_router
from app.config import Settings
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
    return app


app = create_app()
