import { sleep } from 'k6';
import {
  baseUrlEnv,
  commonHttpOptions,
  expectedResponseThresholds,
  getOrders,
  positiveIntegerEnv,
  requiredEnv,
} from './common.js';

export const options = Object.assign(commonHttpOptions(), {
  vus: positiveIntegerEnv('VUS', 50),
  duration: __ENV.DURATION || '30s',
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
  sleep(Number(__ENV.SLEEP_SECONDS || 0.1));
}
