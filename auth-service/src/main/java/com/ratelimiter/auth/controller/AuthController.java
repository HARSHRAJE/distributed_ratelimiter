package com.ratelimiter.auth.controller;

import com.ratelimiter.auth.dto.AuthResponse;
import com.ratelimiter.auth.dto.LoginRequest;
import com.ratelimiter.auth.dto.RegisterRequest;
import com.ratelimiter.auth.dto.RegisterResponse;
import com.ratelimiter.auth.dto.SelectTenantRequest;
import com.ratelimiter.auth.dto.UserMeResponse;
import com.ratelimiter.auth.service.AuthService;
import com.ratelimiter.auth.service.AuthService.LoginResult;
import jakarta.validation.Valid;
import java.time.Duration;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.core.annotation.AuthenticationPrincipal;
import org.springframework.web.bind.annotation.CookieValue;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public class AuthController {

    private static final String REFRESH_COOKIE = "refresh_token";

    private final AuthService authService;
    private final boolean secureCookie;

    public AuthController(
            AuthService authService,
            @Value("${auth.refresh-token.cookie-secure}") boolean secureCookie) {
        this.authService = authService;
        this.secureCookie = secureCookie;
    }

    @PostMapping("/register")
    public ResponseEntity<RegisterResponse> register(
            @Valid @RequestBody RegisterRequest request) {
        return ResponseEntity.status(201).body(authService.register(request));
    }

    @PostMapping("/login")
    public ResponseEntity<AuthResponse> login(
            @Valid @RequestBody LoginRequest request) {
        LoginResult result = authService.login(request);
        return withRefreshCookie(result);
    }

    @PostMapping("/refresh")
    public ResponseEntity<AuthResponse> refresh(
            @CookieValue(name = REFRESH_COOKIE, required = false)
            String refreshToken) {
        return withRefreshCookie(
            authService.refresh(refreshToken, null, null)
        );
    }

    @PostMapping("/logout")
    public ResponseEntity<Void> logout(
            @CookieValue(name = REFRESH_COOKIE, required = false)
            String refreshToken) {
        authService.logout(refreshToken);
        return ResponseEntity.noContent()
            .header(HttpHeaders.SET_COOKIE, clearRefreshCookie().toString())
            .build();
    }

    @GetMapping("/me")
    public UserMeResponse me(@AuthenticationPrincipal Jwt jwt) {
        return authService.currentUser(
            UUID.fromString(jwt.getSubject()),
            UUID.fromString(jwt.getClaimAsString("tenant_id")),
            jwt.getClaimAsString("tenant_key"),
            jwt.getClaimAsStringList("roles")
        );
    }

    @PostMapping("/select-tenant")
    public ResponseEntity<AuthResponse> selectTenant(
            @AuthenticationPrincipal Jwt jwt,
            @Valid @RequestBody SelectTenantRequest request,
            @CookieValue(name = REFRESH_COOKIE, required = false)
            String refreshToken) {
        LoginResult result = authService.refresh(
            refreshToken,
            UUID.fromString(jwt.getSubject()),
            request.tenantId()
        );
        return withRefreshCookie(result);
    }

    private ResponseEntity<AuthResponse> withRefreshCookie(
            LoginResult result) {
        Duration maxAge = Duration.between(
            java.time.Instant.now(),
            result.refreshExpiresAt()
        );
        ResponseCookie cookie = ResponseCookie.from(
                REFRESH_COOKIE,
                result.rawRefreshToken()
            )
            .httpOnly(true)
            .secure(secureCookie)
            .sameSite("Strict")
            .path("/api/v1/auth")
            .maxAge(maxAge)
            .build();
        return ResponseEntity.ok()
            .header(HttpHeaders.SET_COOKIE, cookie.toString())
            .body(result.response());
    }

    private ResponseCookie clearRefreshCookie() {
        return ResponseCookie.from(REFRESH_COOKIE, "")
            .httpOnly(true)
            .secure(secureCookie)
            .sameSite("Strict")
            .path("/api/v1/auth")
            .maxAge(Duration.ZERO)
            .build();
    }
}
