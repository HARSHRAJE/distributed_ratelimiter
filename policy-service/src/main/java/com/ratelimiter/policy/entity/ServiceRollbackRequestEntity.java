package com.ratelimiter.policy.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import com.ratelimiter.policy.dto.response.ServiceRollbackStatus;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "service_rollback_requests")
public class ServiceRollbackRequestEntity {

    @Id
    @Column(name = "rollback_id", nullable = false)
    private UUID rollbackId;

    @Column(name = "service_id", nullable = false)
    private UUID serviceId;

    @Column(name = "expected_active_version", nullable = false)
    private Long expectedActiveVersion;

    @Column(name = "restored_from_version", nullable = false)
    private Long restoredFromVersion;

    @Column(name = "rollback_version", nullable = false)
    private Long rollbackVersion;

    @Column(name = "global_capacity", nullable = false)
    private Integer globalCapacity;

    @Column(
        name = "global_refill_rate",
        nullable = false,
        precision = 12,
        scale = 3
    )
    private BigDecimal globalRefillRate;

    @Column(name = "accepted_at", nullable = false, updatable = false)
    private Instant acceptedAt;

    protected ServiceRollbackRequestEntity() {}

    public ServiceRollbackRequestEntity(
            UUID rollbackId,
            ServiceEntity service,
            Long expectedActiveVersion,
            Long restoredFromVersion) {
        this.rollbackId = rollbackId;
        this.serviceId = service.getId();
        this.expectedActiveVersion = expectedActiveVersion;
        this.restoredFromVersion = restoredFromVersion;
        this.rollbackVersion = service.getConfigVersion();
        this.globalCapacity = service.getGlobalCapacity();
        this.globalRefillRate = service.getGlobalRefillRate();
        this.acceptedAt = Instant.now();
    }

    public UUID getServiceId() {
        return serviceId;
    }

    public Long getExpectedActiveVersion() {
        return expectedActiveVersion;
    }

    public Long getRestoredFromVersion() {
        return restoredFromVersion;
    }

    public Long getRollbackVersion() {
        return rollbackVersion;
    }

    public Integer getGlobalCapacity() {
        return globalCapacity;
    }

    public BigDecimal getGlobalRefillRate() {
        return globalRefillRate;
    }

    public ServiceRollbackStatus toStatus() {
        return new ServiceRollbackStatus(
            rollbackId,
            serviceId,
            expectedActiveVersion,
            restoredFromVersion,
            rollbackVersion,
            globalCapacity,
            globalRefillRate,
            false
        );
    }
}
