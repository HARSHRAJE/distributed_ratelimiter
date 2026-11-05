import http from 'k6/http';
import { check } from 'k6';
import { Counter, Rate } from 'k6/metrics';

const allowed = new Counter('rate_limit_allowed');
const rejected = new Counter('rate_limit_rejected');
const unexpected = new Counter('rate_limit_unexpected');
const acceptedRate = new Rate('rate_limit_accepted_rate');

export const options = {
  stages: [
    { duration: '20s', target: 100 },
    { duration: '30s', target: 100 },
    { duration: '20s', target: 500 },
    { duration: '30s', target: 500 },
    { duration: '20s', target: 1000 },
    { duration: '30s', target: 1000 },
    { duration: '10s', target: 0 },
  ],
  thresholds: {
    rate_limit_unexpected: ['count==0'],
  },
};

export default function () {
  const response = http.get(`${__ENV.BASE_URL}/api/orders`, {
    headers: {
      Authorization: `Bearer ${__ENV.ACCESS_TOKEN}`,
    },
    tags: { name: 'GET /api/orders' },
  });

  const isAllowed = response.status === 200;
  const isRateLimited = response.status === 429;
  if (isAllowed) {
    allowed.add(1);
  } else if (isRateLimited) {
    rejected.add(1);
  } else {
    unexpected.add(1);
  }
  acceptedRate.add(isAllowed);

  check(response, {
    'response is allowed or rate limited': () =>
      isAllowed || isRateLimited,
  });
}
