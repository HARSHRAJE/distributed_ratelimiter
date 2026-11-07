package com.ratelimiter.auth.entity;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.util.UUID;

@Entity
@Table(name = "tenant_memberships")
public class TenantMembershipEntity {

    @Id
    private UUID id;

    @Column(name = "user_id", nullable = false)
    private UUID userId;

    @Column(name = "tenant_id", nullable = false)
    private UUID tenantId;

    @Column(nullable = false, length = 30)
    private String role;

    protected TenantMembershipEntity() {}

    public TenantMembershipEntity(
            UUID id,
            UUID userId,
            UUID tenantId,
            String role) {
        this.id = id;
        this.userId = userId;
        this.tenantId = tenantId;
        this.role = role;
    }

    public UUID getId() { return id; }
    public UUID getUserId() { return userId; }
    public UUID getTenantId() { return tenantId; }
    public String getRole() { return role; }
}
