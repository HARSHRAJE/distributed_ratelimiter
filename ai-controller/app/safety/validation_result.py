from datetime import datetime
from uuid import UUID

from app.safety.schemas import ValidationCheck, ValidationResult, ValidationStatus

VALIDATOR_VERSION = "1.0"


def build_validation_result(
    *,
    validation_id: UUID,
    recommendation_id: UUID,
    checks: list[ValidationCheck],
    validated_at: datetime,
) -> ValidationResult:
    status = (
        ValidationStatus.VALID
        if all(check.passed for check in checks)
        else ValidationStatus.REJECTED
    )
    return ValidationResult(
        id=validation_id,
        recommendation_id=recommendation_id,
        status=status,
        checks=checks,
        validated_at=validated_at,
        validator_version=VALIDATOR_VERSION,
    )
