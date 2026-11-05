import {
  baseUrlEnv,
  commonHttpOptions,
  expectedResponseThresholds,
  getOrders,
  positiveIntegerEnv,
  requiredEnv,
} from './common.js';

export const options = Object.assign(commonHttpOptions(), {
  scenarios: {
    gateway_1: {
      executor: 'constant-vus',
      exec: 'gateway1',
      vus: positiveIntegerEnv('VUS_PER_GATEWAY', 25),
      duration: __ENV.DURATION || '30s',
    },
    gateway_2: {
      executor: 'constant-vus',
      exec: 'gateway2',
      vus: positiveIntegerEnv('VUS_PER_GATEWAY', 25),
      duration: __ENV.DURATION || '30s',
    },
  },
  thresholds: expectedResponseThresholds(),
});

export function setup() {
  return {
    token: requiredEnv('ACCESS_TOKEN'),
    gateway1: baseUrlEnv('GATEWAY_1_URL', 'http://localhost:8080'),
    gateway2: baseUrlEnv('GATEWAY_2_URL', 'http://localhost:8081'),
  };
}

export function gateway1(data) {
  getOrders(data.gateway1, data.token, { gateway: 'gateway-1' });
}

export function gateway2(data) {
  getOrders(data.gateway2, data.token, { gateway: 'gateway-2' });
}
