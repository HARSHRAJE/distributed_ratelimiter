import numpy as np
import pandas as pd


def calculate_features(
    observations: pd.DataFrame,
    *,
    interval_seconds: int = 15,
) -> pd.DataFrame:
    if interval_seconds < 1:
        raise ValueError("interval_seconds must be positive")
    if "incoming_rps" not in observations:
        raise ValueError("incoming_rps is required")

    frame = observations.copy()
    incoming = pd.to_numeric(frame["incoming_rps"], errors="coerce")
    frame["incoming_rps"] = incoming.where(
        np.isfinite(incoming) & (incoming >= 0)
    )
    one_minute = max(1, round(60 / interval_seconds))
    five_minutes = max(1, round(300 / interval_seconds))
    frame["rps_avg_1m"] = frame["incoming_rps"].rolling(
        one_minute,
        min_periods=one_minute,
    ).mean()
    frame["rps_avg_5m"] = frame["incoming_rps"].rolling(
        five_minutes,
        min_periods=five_minutes,
    ).mean()
    frame["rps_max_5m"] = frame["incoming_rps"].rolling(
        five_minutes,
        min_periods=five_minutes,
    ).max()
    previous_rps = frame["incoming_rps"].shift(1)
    frame["rps_change"] = (
        frame["incoming_rps"] - previous_rps
    ) / previous_rps.where(previous_rps > 0)
    frame["rps_variance_5m"] = frame["incoming_rps"].rolling(
        five_minutes,
        min_periods=five_minutes,
    ).var()

    if "rejected_rps" in frame:
        rejected = pd.to_numeric(frame["rejected_rps"], errors="coerce")
        rejected = rejected.where(np.isfinite(rejected) & (rejected >= 0))
        denominator = frame["incoming_rps"].where(frame["incoming_rps"] > 0)
        frame["rejection_ratio"] = rejected / denominator
    else:
        frame["rejection_ratio"] = float("nan")

    if "p95_latency_ms" in frame:
        latency = pd.to_numeric(frame["p95_latency_ms"], errors="coerce")
        latency = latency.where(np.isfinite(latency) & (latency >= 0))
        frame["latency_trend"] = latency.diff()
    else:
        frame["latency_trend"] = float("nan")
    return frame
