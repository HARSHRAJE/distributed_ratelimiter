from ipaddress import ip_address
from uuid import uuid4

from sqlalchemy.orm import Session

from app.telemetry.models import SecurityAuditEventRecord


def record_security_event(
    session: Session,
    *,
    actor_id: str | None,
    tenant_id: str | None,
    service_key: str | None,
    event_type: str,
    resource_id: str | None,
    outcome: str,
    source_ip: str | None,
    details: dict | None = None,
) -> None:
    if source_ip is not None:
        try:
            source_ip = str(ip_address(source_ip))
        except ValueError:
            source_ip = None
    session.add(SecurityAuditEventRecord(
        id=uuid4(),
        actor_id=actor_id,
        tenant_id=tenant_id,
        service_key=service_key,
        event_type=event_type,
        resource_id=resource_id,
        outcome=outcome,
        source_ip=source_ip,
        details=details,
    ))
    session.commit()
