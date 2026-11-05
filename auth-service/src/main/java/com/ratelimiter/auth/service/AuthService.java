package com.ratelimiter.auth.service;

import com.ratelimiter.auth.dto.AuthResponse;
import com.ratelimiter.auth.dto.LoginRequest;
import com.ratelimiter.auth.dto.RegisterRequest;
import com.ratelimiter.auth.dto.RegisterResponse;
import com.ratelimiter.auth.dto.UserMeResponse;
import com.ratelimiter.auth.entity.TenantEntity;
import com.ratelimiter.auth.entity.TenantMembershipEntity;
import com.ratelimiter.auth.entity.UserEntity;
import com.ratelimiter.auth.exception.EmailAlreadyRegisteredException;
import com.ratelimiter.auth.exception.InvalidCredentialsException;
import com.ratelimiter.auth.exception.InvalidTokenException;
import com.ratelimiter.auth.repository.RefreshTokenRepository;
import com.ratelimiter.auth.repository.TenantMembershipRepository;
import com.ratelimiter.auth.repository.TenantRepository;
import com.ratelimiter.auth.repository.UserRepository;
import com.ratelimiter.auth.service.LoginAttemptService.AttemptState;
import com.ratelimiter.auth.service.RefreshTokenService.IssuedRefreshToken;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class AuthService {

    private final UserRepository userRepository;
    private final TenantRepository tenantRepository;
    private final TenantMembershipRepository membershipRepository;
    private final RefreshTokenRepository refreshTokenRepository;
    private final PasswordEncoder passwordEncoder;
    private final LoginAttemptService loginAttemptService;
    private final RefreshTokenService refreshTokenService;
    private final JwtService jwtService;
    private final String dummyPasswordHash;
    private final int maximumFailedAttempts;
    private final Duration lockDuration;

    public AuthService(
            UserRepository userRepository,
            TenantRepository tenantRepository,
            TenantMembershipRepository membershipRepository,
            RefreshTokenRepository refreshTokenRepository,
            PasswordEncoder passwordEncoder,
            LoginAttemptService loginAttemptService,
            RefreshTokenService refreshTokenService,
            JwtService jwtService,
            @Value("${auth.login.max-failed-attempts}") int maximumFailedAttempts,
            @Value("${auth.login.lock-duration}") Duration lockDuration) {

        this.userRepository = userRepository;
        this.tenantRepository = tenantRepository;
        this.membershipRepository = membershipRepository;
        this.refreshTokenRepository = refreshTokenRepository;
        this.passwordEncoder = passwordEncoder;
        this.loginAttemptService = loginAttemptService;
        this.refreshTokenService = refreshTokenService;
        this.jwtService = jwtService;
        this.dummyPasswordHash =
            passwordEncoder.encode(UUID.randomUUID().toString());
        this.maximumFailedAttempts = maximumFailedAttempts;
        this.lockDuration = lockDuration;
    }

    @Transactional
    public RegisterResponse register(RegisterRequest request) {
        String email = normalizeEmail(request.email());
        validatePasswordSize(request.password());
        if (userRepository.existsByEmail(email)) {
            throw new EmailAlreadyRegisteredException();
        }

        UserEntity user = new UserEntity(
            UUID.randomUUID(),
            email,
            passwordEncoder.encode(request.password())
        );
        userRepository.saveAndFlush(user);
        return new RegisterResponse(user.getId(), user.getEmail());
    }

    @Transactional(noRollbackFor = InvalidCredentialsException.class)
    public LoginResult login(LoginRequest request) {
        String email = normalizeEmail(request.email());
        Instant now = Instant.now();
        AttemptState attempt = loginAttemptService.lock(email);
        if (attempt.lockedUntil() != null
                && attempt.lockedUntil().isAfter(now)) {
            throw new InvalidCredentialsException();
        }

        UserEntity user = userRepository.findByEmail(email).orElse(null);
        boolean passwordMatches = passwordEncoder.matches(
            request.password(),
            user == null || request.password()
                    .getBytes(StandardCharsets.UTF_8).length > 72
                ? dummyPasswordHash
                : user.getPasswordHash()
        );

        TenantMembershipEntity membership = user == null
            ? null
            : membershipRepository
                .findByUserIdAndTenantId(user.getId(), request.tenantId())
                .orElse(null);

        if (user == null || !user.isEnabled() || !passwordMatches
                || membership == null) {
            loginAttemptService.recordFailure(
                email,
                attempt,
                maximumFailedAttempts,
                now,
                now.plus(lockDuration)
            );
            throw new InvalidCredentialsException();
        }

        TenantEntity tenant = tenantRepository.findById(request.tenantId())
            .orElseThrow(InvalidCredentialsException::new);

        loginAttemptService.clear(email);
        IssuedRefreshToken refreshToken = refreshTokenService.issue(
            user.getId(),
            tenant.getId()
        );
        return new LoginResult(
            authResponse(user, tenant, membership),
            refreshToken.rawToken(),
            refreshToken.expiresAt()
        );
    }

    @Transactional(noRollbackFor = InvalidTokenException.class)
    public LoginResult refresh(
            String rawRefreshToken,
            UUID expectedUserId,
            UUID targetTenantId) {

        IssuedRefreshToken refreshToken = refreshTokenService.rotate(
            rawRefreshToken,
            expectedUserId,
            targetTenantId
        );

        UserEntity user = userRepository.findById(refreshToken.userId())
            .orElseThrow(InvalidTokenException::new);
        TenantMembershipEntity membership = membershipRepository
            .findByUserIdAndTenantId(
                user.getId(),
                refreshToken.tenantId()
            )
            .orElse(null);
        TenantEntity tenant = tenantRepository.findById(
            refreshToken.tenantId()
        ).orElse(null);

        if (!user.isEnabled() || membership == null || tenant == null) {
            refreshTokenRepository.revokeAllActiveForUser(user.getId());
            throw new InvalidTokenException();
        }

        return new LoginResult(
            authResponse(user, tenant, membership),
            refreshToken.rawToken(),
            refreshToken.expiresAt()
        );
    }

    @Transactional
    public void logout(String rawRefreshToken) {
        refreshTokenService.revoke(rawRefreshToken);
    }

    @Transactional(readOnly = true)
    public UserMeResponse currentUser(
            UUID userId,
            UUID tenantId,
            String tenantKey,
            List<String> roles) {

        UserEntity user = userRepository.findById(userId)
            .filter(UserEntity::isEnabled)
            .orElseThrow(InvalidTokenException::new);
        return new UserMeResponse(
            user.getId(),
            user.getEmail(),
            tenantId,
            tenantKey,
            List.copyOf(roles)
        );
    }

    private AuthResponse authResponse(
            UserEntity user,
            TenantEntity tenant,
            TenantMembershipEntity membership) {
        return new AuthResponse(
            jwtService.issueAccessToken(user, tenant, membership),
            "Bearer",
            jwtService.accessTokenTtlSeconds(),
            user.getId(),
            tenant.getId(),
            tenant.getTenantKey(),
            List.of(membership.getRole())
        );
    }

    private String normalizeEmail(String email) {
        return email.trim().toLowerCase(Locale.ROOT);
    }

    private void validatePasswordSize(String password) {
        if (password.getBytes(StandardCharsets.UTF_8).length > 72) {
            throw new IllegalArgumentException(
                "Password must not exceed 72 UTF-8 bytes"
            );
        }
    }

    public record LoginResult(
        AuthResponse response,
        String rawRefreshToken,
        Instant refreshExpiresAt
    ) {}
}
