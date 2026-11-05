import {
  baseUrlEnv,
  commonHttpOptions,
  expectedResponseThresholds,
  getOrders,
  positiveIntegerEnv,
  requiredEnv,
} from './common.js';

const thresholds = expectedResponseThresholds();
if (__ENV.EXPECTED_MAX_ALLOWED !== undefined) {
  const maximum = positiveIntegerEnv('EXPECTED_MAX_ALLOWED', 1);
  thresholds.load_test_allowed_responses = [`count<=${maximum}`];
}

export const options = Object.assign(commonHttpOptions(), {
  scenarios: {
    concurrent_requests: {
      executor: 'per-vu-iterations',
      vus: positiveIntegerEnv('VUS', 100),
      iterations: 1,
      maxDuration: __ENV.MAX_DURATION || '30s',
    },
  },
  thresholds,
});

export function setup() {
  return {
    baseUrl: baseUrlEnv('BASE_URL', 'http://localhost:8080'),
    token: requiredEnv('ACCESS_TOKEN'),
  };
}

export default function (data) {
  getOrders(data.baseUrl, data.token, { test: 'concurrent-single-wave' });
}
