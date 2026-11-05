package com.ratelimiter.policy.redis;

import java.util.List;
import com.ratelimiter.policy.dto.response.ServiceConfigSnapshot;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Component
public class RedisServiceConfigWriter {

    private static final String UPDATE_SCRIPT = """
        local function is_positive_integer(value)
            local number = tonumber(value)
            return number ~= nil
                and number > 0
                and number == math.floor(number)
        end

        local incomingVersion = tonumber(ARGV[1])
        if not is_positive_integer(incomingVersion) then
            return redis.error_reply('Invalid incoming config version')
        end

        local incomingOk, incoming = pcall(cjson.decode, ARGV[2])
        if not incomingOk or type(incoming) ~= 'table'
            or tonumber(incoming.configVersion) ~= incomingVersion then
            return redis.error_reply('Malformed incoming service config snapshot')
        end

        local keyType = redis.call('TYPE', KEYS[1]).ok
        if keyType ~= 'none' and keyType ~= 'string' then
            return redis.error_reply('Unexpected service config Redis type')
        end

        if keyType == 'string' then
            local currentOk, current = pcall(
                cjson.decode,
                redis.call('GET', KEYS[1])
            )
            if not currentOk or type(current) ~= 'table'
                or not is_positive_integer(current.configVersion) then
                return redis.error_reply('Malformed existing service config snapshot')
            end
            if tonumber(current.configVersion) >= incomingVersion then
                return 0
            end
        end

        redis.call('SET', KEYS[1], ARGV[2])
        return 1
        """;

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final DefaultRedisScript<Long> updateScript =
        new DefaultRedisScript<>(UPDATE_SCRIPT, Long.class);

    public RedisServiceConfigWriter(
            StringRedisTemplate redisTemplate,
            ObjectMapper objectMapper) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
    }

    public boolean write(ServiceConfigSnapshot snapshot) {
        String key = "rl:service-config:{" + snapshot.serviceKey() + "}";
        try {
            String payload = objectMapper.writeValueAsString(snapshot);
            Long result = redisTemplate.execute(
                updateScript,
                List.of(key),
                snapshot.configVersion().toString(),
                payload
            );
            return Long.valueOf(1).equals(result);
        } catch (JacksonException ex) {
            throw new IllegalStateException(
                "Unable to serialize service configuration snapshot",
                ex
            );
        }
    }
}
