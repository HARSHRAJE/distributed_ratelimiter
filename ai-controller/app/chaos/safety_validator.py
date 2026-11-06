from dataclasses import dataclass


@dataclass(frozen=True)
class SafetyAssessment:
    policy_consistency: bool
    safety_violations: int
    checks: dict[str, bool | None]


class SafetyValidator:
    def assess(
        self,
        *,
        fault_observations: list[dict],
        recovery_observations: list[dict],
        policy_version_before: int | None = None,
        policy_version_after: int | None = None,
        disabled_policy_before: bool | None = None,
        disabled_policy_after: bool | None = None,
    ) -> SafetyAssessment:
        no_unexpected_success = bool(fault_observations) and all(
            item.get("status_code") == 503
            for item in fault_observations
        )
        service_recovers = bool(recovery_observations) and any(
            item.get("status_code") in {200, 201, 202, 204, 429}
            for item in recovery_observations
        )
        version_consistent = (
            None
            if policy_version_before is None or policy_version_after is None
            else policy_version_after >= policy_version_before
        )
        disabled_state_preserved = (
            None
            if disabled_policy_before is None or disabled_policy_after is None
            else not disabled_policy_before or disabled_policy_after
        )
        checks = {
            "fail_closed_during_redis_outage": no_unexpected_success,
            "protected_route_recovers": service_recovers,
            "policy_version_did_not_regress": version_consistent,
            "disabled_policy_was_not_resurrected": disabled_state_preserved,
        }
        return SafetyAssessment(
            policy_consistency=(
                version_consistent is True
                and disabled_state_preserved is True
            ),
            safety_violations=sum(
                passed is False for passed in checks.values()
            ),
            checks=checks,
        )
