package com.ratelimiter.policy.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import jakarta.persistence.UniqueConstraint;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(
    name = "service_config_versions",
    uniqueConstraints = @UniqueConstraint(
        name = "uq_service_config_versions_service_version",
        columnNames = {"service_id", "config_version"}
    )
)
public class ServiceConfigVersionEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "service_id", nullable = false)
    private UUID serviceId;

    @Column(name = "config_version", nullable = false)
    private Long configVersion;

    @Column(name = "global_capacity", nullable = false)
    private Integer globalCapacity;

    @Column(
        name = "global_refill_rate",
        nullable = false,
        precision = 12,
        scale = 3
    )
    private BigDecimal globalRefillRate;

    @Column(name = "adaptive_enabled", nullable = false)
    private Boolean adaptiveEnabled;

    @Column(name = "source", nullable = false, length = 32)
    private String source;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    protected ServiceConfigVersionEntity() {}

    public ServiceConfigVersionEntity(
            ServiceEntity service,
            String source) {
        this.serviceId = service.getId();
        this.configVersion = service.getConfigVersion();
        this.globalCapacity = service.getGlobalCapacity();
        this.globalRefillRate = service.getGlobalRefillRate();
        this.adaptiveEnabled = service.getAdaptiveEnabled();
        this.source = source;
        this.createdAt = Instant.now();
    }

    public Long getConfigVersion() {
        return configVersion;
    }

    public Integer getGlobalCapacity() {
        return globalCapacity;
    }

    public BigDecimal getGlobalRefillRate() {
        return globalRefillRate;
    }
}
