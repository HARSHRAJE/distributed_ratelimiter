import http from 'k6/http';
import { check } from 'k6';
import { Counter } from 'k6/metrics';

export const allowedResponses = new Counter('load_test_allowed_responses');
export const rateLimitedResponses = new Counter(
  'load_test_rate_limited_responses',
);
export const unexpectedResponses = new Counter(
  'load_test_unexpected_responses',
);

export function positiveIntegerEnv(name, defaultValue) {
  const raw = __ENV[name];
  if (raw === undefined || raw === '') {
    return defaultValue;
  }

  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value <= 0) {
    throw new Error(`${name} must be a positive integer.`);
  }
  return value;
}

export function requiredEnv(name) {
  const value = __ENV[name];
  if (!value) {
    throw new Error(`Set ${name} to run this scenario.`);
  }
  return value;
}

export function baseUrlEnv(name, defaultValue) {
  const value = __ENV[name] || defaultValue;
  return value.replace(/\/+$/, '');
}

export function expectedResponseThresholds() {
  return {
    load_test_unexpected_responses: ['count==0'],
    checks: ['rate==1'],
  };
}

export function getOrders(baseUrl, token, extraTags = {}) {
  const tags = Object.assign(
    { name: 'GET /api/orders' },
    extraTags,
  );
  const response = http.get(`${baseUrl}/api/orders`, {
    headers: {
      Authorization: `Bearer ${token}`,
    },
    timeout: __ENV.REQUEST_TIMEOUT || '10s',
    responseCallback: http.expectedStatuses(200, 429),
    tags,
  });

  const allowed = response.status === 200;
  const rateLimited = response.status === 429;
  const expected = allowed || rateLimited;

  if (allowed) {
    allowedResponses.add(1, extraTags);
  } else if (rateLimited) {
    rateLimitedResponses.add(1, extraTags);
  } else {
    unexpectedResponses.add(1, Object.assign(
      { status: String(response.status) },
      extraTags,
    ));
  }

  check(response, {
    'response is allowed or rate limited': () => expected,
  }, extraTags);

  return response;
}

export function commonHttpOptions() {
  return {
    discardResponseBodies: true,
    summaryTrendStats: [
      'avg',
      'min',
      'med',
      'max',
      'p(50)',
      'p(95)',
      'p(99)',
    ],
  };
}
