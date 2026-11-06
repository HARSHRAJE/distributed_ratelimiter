package com.ratelimiter.policy.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;

@Entity
@Table(name = "policy_execution_control")
public class PolicyExecutionControlEntity {

    @Id
    @Column(name = "id", nullable = false, length = 20)
    private String id;

    @Column(name = "kill_switch_active", nullable = false)
    private Boolean killSwitchActive;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    protected PolicyExecutionControlEntity() {}

    public String getId() {
        return id;
    }

    public Boolean getKillSwitchActive() {
        return killSwitchActive;
    }

    public void setKillSwitchActive(Boolean killSwitchActive) {
        this.killSwitchActive = killSwitchActive;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Instant updatedAt) {
        this.updatedAt = updatedAt;
    }
}
