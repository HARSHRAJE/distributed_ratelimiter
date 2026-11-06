from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.security.audit import record_security_event
from app.telemetry.models import Base, SecurityAuditEventRecord


def test_security_audit_persists_identity_and_safe_metadata_only():
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        record_security_event(
            session,
            actor_id="AI_CONTROLLER",
            tenant_id=None,
            service_key="orders-service",
            event_type="POLICY_RECOMMENDATION_EXECUTION",
            resource_id="recommendation-123",
            outcome="APPLIED",
            source_ip="127.0.0.1",
            details={"resulting_policy_version": 4},
        )
        record = session.scalar(
            select(SecurityAuditEventRecord)
        )

        assert record is not None
        assert record.actor_id == "AI_CONTROLLER"
        assert record.service_key == "orders-service"
        assert record.source_ip == "127.0.0.1"
        assert record.details == {"resulting_policy_version": 4}
        assert "token" not in repr(record.details).lower()

    engine.dispose()
