
package com.ratelimiter.policy.entity;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "services")
public class ServiceEntity {

    @Id
    @GeneratedValue(strategy = GenerationType.UUID)
    private UUID id;

    @Column(name = "service_key", nullable = false, unique = true, length = 100)
    private String serviceKey;

    @Column(name = "global_capacity", nullable = false)
    private Integer globalCapacity;

    @Column(name = "global_refill_rate", nullable = false, precision = 12, scale = 3)
    private BigDecimal globalRefillRate;

    @Column(name = "hard_max_refill_rate", nullable = false, precision = 12, scale = 3)
    private BigDecimal hardMaxRefillRate;

    @Column(name = "config_version", nullable = false)
    private Long configVersion = 1L;

    @Column(name = "adaptive_enabled", nullable = false)
    private Boolean adaptiveEnabled = false;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "updated_at", nullable = false)
    private Instant updatedAt;

    @PrePersist
    protected void onCreate() {
        Instant now = Instant.now();
        createdAt = now;
        updatedAt = now;
    }

    @PreUpdate
    protected void onUpdate() {
        updatedAt = Instant.now();
    }

    public ServiceEntity() {}

    public UUID getId() {
        return id;
    }

    public void setId(UUID id) {
        this.id = id;
    }

    public String getServiceKey() {
        return serviceKey;
    }

    public void setServiceKey(String serviceKey) {
        this.serviceKey = serviceKey;
    }

    public Integer getGlobalCapacity() {
        return globalCapacity;
    }

    public void setGlobalCapacity(Integer globalCapacity) {
        this.globalCapacity = globalCapacity;
    }

    public BigDecimal getGlobalRefillRate() {
        return globalRefillRate;
    }

    public void setGlobalRefillRate(BigDecimal globalRefillRate) {
        this.globalRefillRate = globalRefillRate;
    }

    public BigDecimal getHardMaxRefillRate() {
        return hardMaxRefillRate;
    }

    public void setHardMaxRefillRate(BigDecimal hardMaxRefillRate) {
        this.hardMaxRefillRate = hardMaxRefillRate;
    }

    public Long getConfigVersion() {
        return configVersion;
    }

    public void setConfigVersion(Long configVersion) {
        this.configVersion = configVersion;
    }

    public Boolean getAdaptiveEnabled() {
        return adaptiveEnabled;
    }

    public void setAdaptiveEnabled(Boolean adaptiveEnabled) {
        this.adaptiveEnabled = adaptiveEnabled;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public Instant getUpdatedAt() {
        return updatedAt;
    }

    public void setUpdatedAt(Instant updatedAt) {
        this.updatedAt = updatedAt;
    }
}
