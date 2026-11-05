package com.ratelimiter.auth.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "tenants")
public class TenantEntity {

    @Id
    private UUID id;

    @Column(name = "tenant_key", nullable = false, unique = true, length = 128)
    private String tenantKey;

    @Column(nullable = false, length = 255)
    private String name;

    @Column(name = "created_at", nullable = false, updatable = false)
    private Instant createdAt;

    protected TenantEntity() {}

    public UUID getId() { return id; }
    public String getTenantKey() { return tenantKey; }
    public String getName() { return name; }
    public Instant getCreatedAt() { return createdAt; }
}
