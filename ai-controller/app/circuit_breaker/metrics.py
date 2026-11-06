from app.circuit_breaker.schemas import BreakerState
from app.forecasting.metrics import BREAKER_STATE


def publish_breaker_state(service_key: str, state: str) -> None:
    for candidate in BreakerState:
        BREAKER_STATE.labels(service_key, candidate.value).set(
            1 if candidate.value == state else 0
        )
