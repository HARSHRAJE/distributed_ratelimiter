package com.ratelimiter.policy.redis;

import com.ratelimiter.policy.dto.response.ServiceConfigSnapshot;
import java.util.Optional;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Component
public class RedisServiceConfigReader {

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;

    public RedisServiceConfigReader(
            StringRedisTemplate redisTemplate,
            ObjectMapper objectMapper) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
    }

    public Optional<ServiceConfigSnapshot> get(String serviceKey) {
        String key = "rl:service-config:{" + serviceKey + "}";
        String payload = redisTemplate.opsForValue().get(key);
        if (payload == null) {
            return Optional.empty();
        }
        try {
            return Optional.of(
                objectMapper.readValue(payload, ServiceConfigSnapshot.class)
            );
        } catch (JacksonException ex) {
            throw new IllegalStateException(
                "Unable to deserialize effective service configuration",
                ex
            );
        }
    }
}
