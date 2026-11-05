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
    tenant_a: {
      executor: 'constant-vus',
      exec: 'tenantA',
      vus: positiveIntegerEnv('VUS_PER_TENANT', 25),
      duration: __ENV.DURATION || '30s',
    },
    tenant_b: {
      executor: 'constant-vus',
      exec: 'tenantB',
      vus: positiveIntegerEnv('VUS_PER_TENANT', 25),
      duration: __ENV.DURATION || '30s',
    },
  },
  thresholds: expectedResponseThresholds(),
});

export function setup() {
  return {
    baseUrl: baseUrlEnv('BASE_URL', 'http://localhost:8080'),
    tenantAToken: requiredEnv('TENANT_A_TOKEN'),
    tenantBToken: requiredEnv('TENANT_B_TOKEN'),
  };
}

export function tenantA(data) {
  getOrders(data.baseUrl, data.tenantAToken, { tenant: 'A' });
}

export function tenantB(data) {
  getOrders(data.baseUrl, data.tenantBToken, { tenant: 'B' });
}
