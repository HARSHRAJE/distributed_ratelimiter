
package com.ratelimiter.policy.entity;

import jakarta.persistence.*;
import java.math.BigDecimal;
import java.time.Instant;

@Entity
@Table(name = "rate_limit_policy_versions")
public class RateLimitPolicyVersionEntity {

    @EmbeddedId
    private PolicyVersionId id;

    @MapsId("policyId")
    @ManyToOne(fetch = FetchType.LAZY, optional = false)
    @JoinColumn(name = "policy_id", nullable = false)
    private RateLimitPolicyEntity policy;

    @Column(name = "tenant_capacity", nullable = false)
    private Integer tenantCapacity;

    @Column(name = "tenant_refill_rate", nullable = false, precision = 12, scale = 3)
    private BigDecimal tenantRefillRate;

    @Column(name = "route_capacity", nullable = false)
    private Integer routeCapacity;

    @Column(name = "route_refill_rate", nullable = false, precision = 12, scale = 3)
    private BigDecimal routeRefillRate;

    @Column(name = "min_refill_rate", nullable = false, precision = 12, scale = 3)
    private BigDecimal minRefillRate;

    @Column(name = "max_refill_rate", nullable = false, precision = 12, scale = 3)
    private BigDecimal maxRefillRate;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 20)
    private PolicySource source;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    @Column(name = "created_by", nullable = false, length = 128)
    private String createdBy;

    @PrePersist
    protected void onCreate() {
        createdAt = Instant.now();
    }

    public RateLimitPolicyVersionEntity() {}

    public PolicyVersionId getId() {
        return id;
    }

    public void setId(PolicyVersionId id) {
        this.id = id;
    }

    public RateLimitPolicyEntity getPolicy() {
        return policy;
    }

    public void setPolicy(RateLimitPolicyEntity policy) {
        this.policy = policy;
    }

    public Integer getTenantCapacity() {
        return tenantCapacity;
    }

    public void setTenantCapacity(Integer tenantCapacity) {
        this.tenantCapacity = tenantCapacity;
    }

    public BigDecimal getTenantRefillRate() {
        return tenantRefillRate;
    }

    public void setTenantRefillRate(BigDecimal tenantRefillRate) {
        this.tenantRefillRate = tenantRefillRate;
    }

    public Integer getRouteCapacity() {
        return routeCapacity;
    }

    public void setRouteCapacity(Integer routeCapacity) {
        this.routeCapacity = routeCapacity;
    }

    public BigDecimal getRouteRefillRate() {
        return routeRefillRate;
    }

    public void setRouteRefillRate(BigDecimal routeRefillRate) {
        this.routeRefillRate = routeRefillRate;
    }

    public BigDecimal getMinRefillRate() {
        return minRefillRate;
    }

    public void setMinRefillRate(BigDecimal minRefillRate) {
        this.minRefillRate = minRefillRate;
    }

    public BigDecimal getMaxRefillRate() {
        return maxRefillRate;
    }

    public void setMaxRefillRate(BigDecimal maxRefillRate) {
        this.maxRefillRate = maxRefillRate;
    }

    public PolicySource getSource() {
        return source;
    }

    public void setSource(PolicySource source) {
        this.source = source;
    }

    public Instant getCreatedAt() {
        return createdAt;
    }

    public void setCreatedAt(Instant createdAt) {
        this.createdAt = createdAt;
    }

    public String getCreatedBy() {
        return createdBy;
    }

    public void setCreatedBy(String createdBy) {
        this.createdBy = createdBy;
    }
}
