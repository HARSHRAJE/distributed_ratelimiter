local TOKEN_SCALE = 1000000
local MAX_SAFE_INTEGER = 9007199254740991

local function positive_integer(value)
    local number = tonumber(value)
    return number ~= nil
        and number == number
        and number > 0
        and number <= MAX_SAFE_INTEGER
        and number == math.floor(number)
end

local function bucket_state(key, capacity, refill_per_ms, now_ms)
    local key_type = redis.call('TYPE', key).ok
    if key_type ~= 'none' and key_type ~= 'hash' then
        return nil, nil, 'Unexpected bucket Redis type'
    end

    if key_type == 'none' then
        return capacity, now_ms, nil
    end

    local values = redis.call('HMGET', key, 'tokens', 'last_refill_ms')
    if not values[1] or not values[2] then
        return nil, nil, 'Incomplete bucket state'
    end

    local tokens = tonumber(values[1])
    local last_refill_ms = tonumber(values[2])
    if tokens == nil or tokens ~= tokens
        or tokens < 0 or tokens > MAX_SAFE_INTEGER
        or tokens ~= math.floor(tokens)
        or last_refill_ms == nil or last_refill_ms ~= last_refill_ms
        or last_refill_ms < 0 or last_refill_ms > MAX_SAFE_INTEGER
        or last_refill_ms ~= math.floor(last_refill_ms) then
        return nil, nil, 'Malformed bucket state'
    end

    tokens = math.min(tokens, capacity)
    local elapsed_ms = math.max(0, now_ms - last_refill_ms)
    local missing = capacity - tokens
    local elapsed_to_full = math.ceil(missing / refill_per_ms)
    elapsed_ms = math.min(elapsed_ms, elapsed_to_full)
    tokens = math.min(capacity, tokens + refill_per_ms * elapsed_ms)

    return tokens, math.max(now_ms, last_refill_ms), nil
end

local capacities = {}
local refill_rates = {}
for index = 1, 3 do
    local capacity = tonumber(ARGV[(index - 1) * 2 + 1])
    local refill_rate = tonumber(ARGV[(index - 1) * 2 + 2])
    if not positive_integer(capacity) or capacity < TOKEN_SCALE
        or not positive_integer(refill_rate) then
        return redis.error_reply('Invalid bucket capacity or refill rate')
    end
    capacities[index] = capacity
    refill_rates[index] = refill_rate
end

local time = redis.call('TIME')
local now_ms = tonumber(time[1]) * 1000
    + math.floor(tonumber(time[2]) / 1000)

local tokens = {}
local last_refill = {}
for index = 1, 3 do
    local value, timestamp, error_message = bucket_state(
        KEYS[index],
        capacities[index],
        refill_rates[index],
        now_ms
    )
    if error_message then
        return redis.error_reply(error_message)
    end
    tokens[index] = value
    last_refill[index] = timestamp
end

local allowed = true
local retry_after_ms = 0
for index = 1, 3 do
    if tokens[index] < TOKEN_SCALE then
        allowed = false
        local retry = math.ceil(
            (TOKEN_SCALE - tokens[index]) / refill_rates[index]
        )
        retry_after_ms = math.max(retry_after_ms, retry)
    end
end

if allowed then
    for index = 1, 3 do
        tokens[index] = tokens[index] - TOKEN_SCALE
    end
end

for index = 1, 3 do
    redis.call(
        'HSET', KEYS[index],
        'tokens', string.format('%.0f', tokens[index]),
        'last_refill_ms', string.format('%.0f', last_refill[index])
    )
    local ttl_ms = math.max(
        1,
        math.ceil(capacities[index] / refill_rates[index])
    )
    redis.call('PEXPIRE', KEYS[index], ttl_ms)
end

return table.concat({
    allowed and '1' or '0',
    string.format('%.0f', tokens[1]),
    string.format('%.0f', tokens[2]),
    string.format('%.0f', tokens[3]),
    string.format('%.0f', retry_after_ms)
}, '|')
