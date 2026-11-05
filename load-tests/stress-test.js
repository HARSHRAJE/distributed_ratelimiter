import {
  baseUrlEnv,
  commonHttpOptions,
  expectedResponseThresholds,
  getOrders,
  positiveIntegerEnv,
  requiredEnv,
} from './common.js';

const rampDuration = __ENV.STRESS_RAMP_DURATION || '20s';
const holdDuration = __ENV.STRESS_HOLD_DURATION || '30s';

export const options = Object.assign(commonHttpOptions(), {
  stages: [
    { duration: rampDuration, target: positiveIntegerEnv('STRESS_LOW_VUS', 100) },
    { duration: holdDuration, target: positiveIntegerEnv('STRESS_LOW_VUS', 100) },
    { duration: rampDuration, target: positiveIntegerEnv('STRESS_MEDIUM_VUS', 500) },
    { duration: holdDuration, target: positiveIntegerEnv('STRESS_MEDIUM_VUS', 500) },
    { duration: rampDuration, target: positiveIntegerEnv('STRESS_HIGH_VUS', 1000) },
    { duration: holdDuration, target: positiveIntegerEnv('STRESS_HIGH_VUS', 1000) },
    { duration: __ENV.STRESS_COOLDOWN_DURATION || '10s', target: 0 },
  ],
  thresholds: expectedResponseThresholds(),
});

export function setup() {
  return {
    baseUrl: baseUrlEnv('BASE_URL', 'http://localhost:8080'),
    token: requiredEnv('ACCESS_TOKEN'),
  };
}

export default function (data) {
  getOrders(data.baseUrl, data.token);
}
