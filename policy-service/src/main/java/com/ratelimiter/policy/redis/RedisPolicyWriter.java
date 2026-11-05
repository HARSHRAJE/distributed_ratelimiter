package com.ratelimiter.policy.redis;

import com.ratelimiter.policy.dto.response.ActivePolicySnapshot;
import java.util.List;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Component;
import tools.jackson.core.JacksonException;
import tools.jackson.databind.ObjectMapper;

@Component
public class RedisPolicyWriter {

    private static final String UPDATE_SCRIPT = """
        local function is_integer(value, minimum)
            local number = tonumber(value)
            return number ~= nil
                and number >= minimum
                and number == math.floor(number)
        end

        local incomingRevision = tonumber(ARGV[1])
        if not is_integer(incomingRevision, 1) then
            return redis.error_reply('Invalid incoming sync revision')
        end

        local incomingOk, incoming = pcall(cjson.decode, ARGV[2])
        if not incomingOk or type(incoming) ~= 'table'
            or tonumber(incoming.syncRevision) ~= incomingRevision
            or incoming.policyId ~= ARGV[4]
            or type(incoming.tenantId) ~= 'string'
            or type(incoming.routeId) ~= 'string'
            or incoming.tenantId .. '|' .. incoming.routeId ~= ARGV[3]
            or (incoming.status ~= 'ACTIVE'
                and incoming.status ~= 'DISABLED') then
            return redis.error_reply('Malformed incoming policy snapshot')
        end

        local snapshotType = redis.call('TYPE', KEYS[1]).ok
        local indexType = redis.call('TYPE', KEYS[2]).ok
        if snapshotType ~= 'none' and snapshotType ~= 'string'
            and snapshotType ~= 'hash' then
            return redis.error_reply('Unexpected policy snapshot Redis type')
        end
        if indexType ~= 'none' and indexType ~= 'hash' then
            return redis.error_reply('Unexpected policy index Redis type')
        end

        local existingPayload = nil
        if snapshotType == 'string' then
            existingPayload = redis.call('GET', KEYS[1])
        elseif snapshotType == 'hash' then
            existingPayload = redis.call('HGET', KEYS[1], 'payload')
            if not existingPayload then
                return redis.error_reply('Malformed legacy policy snapshot hash')
            end
        end

        if existingPayload then
            local currentOk, current = pcall(cjson.decode, existingPayload)
            if not currentOk or type(current) ~= 'table'
                or type(current.policyId) ~= 'string'
                or type(current.tenantId) ~= 'string'
                or type(current.routeId) ~= 'string'
                or current.policyId ~= ARGV[4] then
                return redis.error_reply('Malformed existing policy snapshot')
            end

            local currentRevision = tonumber(current.syncRevision)
            if currentRevision == nil and snapshotType == 'hash' then
                currentRevision = 0
            end
            if not is_integer(currentRevision, 0) then
                return redis.error_reply('Invalid existing policy sync revision')
            end

            if currentRevision >= incomingRevision then
                redis.call(
                    'HSET', KEYS[2],
                    current.tenantId .. '|' .. current.routeId,
                    current.policyId
                )
                return 0
            end
        end

        redis.call('SET', KEYS[1], ARGV[2])
        redis.call(
            'HSET', KEYS[2],
            incoming.tenantId .. '|' .. incoming.routeId,
            incoming.policyId
        )
        return 1
        """;

    private final StringRedisTemplate redisTemplate;
    private final ObjectMapper objectMapper;
    private final DefaultRedisScript<Long> updateScript =
        new DefaultRedisScript<>(UPDATE_SCRIPT, Long.class);

    public RedisPolicyWriter(
            StringRedisTemplate redisTemplate,
            ObjectMapper objectMapper) {
        this.redisTemplate = redisTemplate;
        this.objectMapper = objectMapper;
    }

    public boolean write(ActivePolicySnapshot snapshot) {
        String serviceTag = "{" + snapshot.serviceKey() + "}";
        String policyKey =
            "rl:policy:" + serviceTag + ":" + snapshot.policyId();
        String indexKey = "rl:policy-index:" + serviceTag;

        try {
            String payload = objectMapper.writeValueAsString(snapshot);
            Long result = redisTemplate.execute(
                updateScript,
                List.of(policyKey, indexKey),
                snapshot.syncRevision().toString(),
                payload,
                snapshot.tenantId() + "|" + snapshot.routeId(),
                snapshot.policyId().toString()
            );
            return Long.valueOf(1).equals(result);
        } catch (JacksonException ex) {
            throw new IllegalStateException(
                "Unable to serialize policy snapshot",
                ex
            );
        }
    }
}
