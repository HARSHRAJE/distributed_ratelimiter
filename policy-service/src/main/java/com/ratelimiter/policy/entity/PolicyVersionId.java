package com.ratelimiter.policy.entity;

import jakarta.persistence.*;
import java.io.Serializable;
import java.util.UUID;
import java.util.Objects;

@Embeddable
public class PolicyVersionId implements Serializable {

    @Column(name = "policy_id")
    private UUID policyId;

    @Column(name = "version")
    private Long version;

    protected PolicyVersionId() {}

    public PolicyVersionId(UUID policyId, Long version) {
        this.policyId = policyId;
        this.version = version;
    }

    public UUID getPolicyId() {
        return policyId;
    }

    public void setPolicyId(UUID policyId) {
        this.policyId = policyId;
    }

    public Long getVersion() {
        return version;
    }

    public void setVersion(Long version) {
        this.version = version;
    }

    @Override
    public boolean equals(Object obj) {
        if (this == obj) return true;
        if (!(obj instanceof PolicyVersionId other)) return false;

        return Objects.equals(policyId, other.policyId)
            && Objects.equals(version, other.version);
    }

    @Override
    public int hashCode() {
        return Objects.hash(policyId, version);
    }
}