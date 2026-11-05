package com.ratelimiter.auth.service;

import com.ratelimiter.auth.entity.TenantEntity;
import com.ratelimiter.auth.entity.TenantMembershipEntity;
import com.ratelimiter.auth.entity.UserEntity;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.security.oauth2.jose.jws.SignatureAlgorithm;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.stereotype.Service;

@Service
public class JwtService {

    private final JwtEncoder jwtEncoder;
    private final String issuer;
    private final String audience;
    private final long accessTokenTtlSeconds;

    public JwtService(
            JwtEncoder jwtEncoder,
            @Value("${auth.jwt.issuer}") String issuer,
            @Value("${auth.jwt.audience}") String audience,
            @Value("${auth.jwt.access-token-ttl}") java.time.Duration accessTokenTtl) {
        this.jwtEncoder = jwtEncoder;
        this.issuer = issuer;
        this.audience = audience;
        this.accessTokenTtlSeconds = accessTokenTtl.toSeconds();
    }

    public String issueAccessToken(
            UserEntity user,
            TenantEntity tenant,
            TenantMembershipEntity membership) {

        Instant now = Instant.now();
        JwtClaimsSet claims = JwtClaimsSet.builder()
            .issuer(issuer)
            .subject(user.getId().toString())
            .audience(List.of(audience))
            .issuedAt(now)
            .expiresAt(now.plusSeconds(accessTokenTtlSeconds))
            .claim("tenant_id", tenant.getId().toString())
            .claim("tenant_key", tenant.getTenantKey())
            .claim("roles", List.of(membership.getRole()))
            .claim("token_type", "access")
            .build();

        return jwtEncoder.encode(JwtEncoderParameters.from(
            JwsHeader.with(SignatureAlgorithm.RS256).build(),
            claims
        )).getTokenValue();
    }

    public long accessTokenTtlSeconds() {
        return accessTokenTtlSeconds;
    }
}
