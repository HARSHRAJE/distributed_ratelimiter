package com.ratelimiter.policy.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "service_execution_requests")
public class ServiceExecutionRequestEntity {

    @Id
    @Column(name = "execution_id", nullable = false)
    private UUID executionId;

    @Column(name = "service_id", nullable = false)
    private UUID serviceId;

    @Column(name = "expected_version", nullable = false)
    private Long expectedVersion;

    @Column(name = "resulting_version", nullable = false)
    private Long resultingVersion;

    @Column(name = "global_capacity", nullable = false)
    private Integer globalCapacity;

    @Column(name = "global_refill_rate", nullable = false, precision = 12, scale = 3)
    private BigDecimal globalRefillRate;

    @Column(name = "accepted_at", nullable = false, updatable = false)
    private Instant acceptedAt;

    protected ServiceExecutionRequestEntity() {}

    public ServiceExecutionRequestEntity(
            UUID executionId,
            UUID serviceId,
            Long expectedVersion,
            Long resultingVersion,
            Integer globalCapacity,
            BigDecimal globalRefillRate) {
        this.executionId = executionId;
        this.serviceId = serviceId;
        this.expectedVersion = expectedVersion;
        this.resultingVersion = resultingVersion;
        this.globalCapacity = globalCapacity;
        this.globalRefillRate = globalRefillRate;
        this.acceptedAt = Instant.now();
    }

    public UUID getExecutionId() {
        return executionId;
    }

    public UUID getServiceId() {
        return serviceId;
    }

    public Long getExpectedVersion() {
        return expectedVersion;
    }

    public Long getResultingVersion() {
        return resultingVersion;
    }

    public Integer getGlobalCapacity() {
        return globalCapacity;
    }

    public BigDecimal getGlobalRefillRate() {
        return globalRefillRate;
    }
}
