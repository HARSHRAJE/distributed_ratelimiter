package com.ratelimiter.auth.service;

import com.ratelimiter.auth.dto.AdminBootstrapRequest;
import com.ratelimiter.auth.dto.AdminBootstrapResponse;
import com.ratelimiter.auth.dto.CreateMembershipRequest;
import com.ratelimiter.auth.dto.CreateTenantRequest;
import com.ratelimiter.auth.dto.MembershipResponse;
import com.ratelimiter.auth.dto.TenantResponse;
import com.ratelimiter.auth.entity.TenantEntity;
import com.ratelimiter.auth.entity.TenantMembershipEntity;
import com.ratelimiter.auth.entity.UserEntity;
import com.ratelimiter.auth.repository.TenantMembershipRepository;
import com.ratelimiter.auth.repository.TenantRepository;
import com.ratelimiter.auth.repository.UserRepository;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Locale;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.ConnectionCallback;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

@Service
public class AdminProvisioningService {

    private static final long BOOTSTRAP_LOCK_ID = 8_194_330_175_010_153L;

    private final TenantRepository tenantRepository;
    private final TenantMembershipRepository membershipRepository;
    private final UserRepository userRepository;
    private final JdbcTemplate jdbcTemplate;
    private final PasswordEncoder passwordEncoder;
    private final String bootstrapToken;

    public AdminProvisioningService(
            TenantRepository tenantRepository,
            TenantMembershipRepository membershipRepository,
            UserRepository userRepository,
            JdbcTemplate jdbcTemplate,
            PasswordEncoder passwordEncoder,
            @Value("${auth.admin.bootstrap-token:}") String bootstrapToken) {
        this.tenantRepository = tenantRepository;
        this.membershipRepository = membershipRepository;
        this.userRepository = userRepository;
        this.jdbcTemplate = jdbcTemplate;
        this.passwordEncoder = passwordEncoder;
        this.bootstrapToken = bootstrapToken;
    }

    @Transactional
    public TenantResponse createTenant(CreateTenantRequest request) {
        return toResponse(saveTenant(request.tenantKey(), request.name()));
    }

    @Transactional
    public MembershipResponse addMembership(
            UUID tenantId,
            CreateMembershipRequest request) {
        TenantEntity tenant = tenantRepository.findById(tenantId)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "Tenant not found"
            ));
        UserEntity user = userRepository.findById(request.userId())
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.NOT_FOUND,
                "User not found"
            ));
        return toResponse(saveMembership(user, tenant, request.role()));
    }

    @Transactional
    public AdminBootstrapResponse bootstrap(
            String suppliedToken,
            AdminBootstrapRequest request) {
        verifyBootstrapToken(suppliedToken);
        acquireBootstrapLock();
        if (membershipRepository.existsByRole(MembershipRole.SUPER_ADMIN.name())) {
            throw new ResponseStatusException(
                HttpStatus.CONFLICT,
                "Admin bootstrap has already been completed"
            );
        }

        UserEntity user = userRepository.findByEmail(
            request.email().trim().toLowerCase(Locale.ROOT)
        ).orElseThrow(() -> new ResponseStatusException(
            HttpStatus.NOT_FOUND,
            "Register this user before admin bootstrap"
        ));
        if (request.initialPassword().getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new ResponseStatusException(
                HttpStatus.BAD_REQUEST,
                "Password must not exceed 72 UTF-8 bytes"
            );
        }
        user.updatePasswordHash(
            passwordEncoder.encode(request.initialPassword())
        );
        TenantEntity tenant = saveTenant(
            request.tenantKey(),
            request.tenantName()
        );
        TenantMembershipEntity membership = saveMembership(
            user,
            tenant,
            MembershipRole.SUPER_ADMIN
        );
        return new AdminBootstrapResponse(
            toResponse(tenant),
            toResponse(membership)
        );
    }

    private TenantEntity saveTenant(String tenantKey, String name) {
        String normalizedKey = tenantKey.trim().toLowerCase(Locale.ROOT);
        if (tenantRepository.existsByTenantKey(normalizedKey)) {
            throw new ResponseStatusException(
                HttpStatus.CONFLICT,
                "Tenant key already exists"
            );
        }
        return tenantRepository.saveAndFlush(new TenantEntity(
            UUID.randomUUID(),
            normalizedKey,
            name.trim()
        ));
    }

    private TenantMembershipEntity saveMembership(
            UserEntity user,
            TenantEntity tenant,
            MembershipRole role) {
        if (membershipRepository.findByUserIdAndTenantId(
                user.getId(),
                tenant.getId()
        ).isPresent()) {
            throw new ResponseStatusException(
                HttpStatus.CONFLICT,
                "User already has a membership in this tenant"
            );
        }
        return membershipRepository.saveAndFlush(new TenantMembershipEntity(
            UUID.randomUUID(),
            user.getId(),
            tenant.getId(),
            role.name()
        ));
    }

    private void verifyBootstrapToken(String suppliedToken) {
        if (bootstrapToken.length() < 32) {
            throw new ResponseStatusException(
                HttpStatus.SERVICE_UNAVAILABLE,
                "Admin bootstrap is not configured"
            );
        }
        if (suppliedToken == null || !MessageDigest.isEqual(
                bootstrapToken.getBytes(StandardCharsets.UTF_8),
                suppliedToken.getBytes(StandardCharsets.UTF_8))) {
            throw new ResponseStatusException(
                HttpStatus.UNAUTHORIZED,
                "Invalid admin bootstrap token"
            );
        }
    }

    private void acquireBootstrapLock() {
        jdbcTemplate.execute((ConnectionCallback<Void>) connection -> {
            try (var statement = connection.prepareStatement(
                    "SELECT pg_advisory_xact_lock(?)")) {
                statement.setLong(1, BOOTSTRAP_LOCK_ID);
                statement.execute();
            }
            return null;
        });
    }

    private static TenantResponse toResponse(TenantEntity tenant) {
        return new TenantResponse(
            tenant.getId(),
            tenant.getTenantKey(),
            tenant.getName(),
            tenant.getCreatedAt()
        );
    }

    private static MembershipResponse toResponse(
            TenantMembershipEntity membership) {
        return new MembershipResponse(
            membership.getId(),
            membership.getUserId(),
            membership.getTenantId(),
            MembershipRole.valueOf(membership.getRole())
        );
    }
}
