import http from "k6/http";
import { Counter, Rate, Trend } from "k6/metrics";

const successful = new Counter("benchmark_successful_requests");
const rateLimited = new Counter("benchmark_rate_limited_requests");
const backendErrors = new Counter("benchmark_backend_errors");
const backendErrorRate = new Rate("benchmark_backend_error_rate");
const rejectionRate = new Rate("benchmark_rejection_rate");
const accepted = new Counter("benchmark_accepted_requests");
const strategyMismatches = new Counter("benchmark_strategy_mismatches");
const tenantDemand = new Counter("benchmark_tenant_demand");
const tenantAccepted = new Counter("benchmark_tenant_accepted");
const acceptedLatency = new Trend("benchmark_accepted_latency_ms");
const backendLatency = new Trend("benchmark_backend_latency_ms");

const stages = JSON.parse(__ENV.BENCHMARK_STAGES || "[]").map((stage) => ({
  duration: `${stage.duration}s`,
  target: stage.target,
}));
const routePaths = (__ENV.BENCHMARK_ROUTE_PATHS || "/").split(",");
const tenantTokens = JSON.parse(__ENV.BENCHMARK_TENANT_TOKENS || "[]");
const config = {
  scenarios: {
    workload: {
      executor: "ramping-arrival-rate",
      startRate: Number(__ENV.BENCHMARK_START_RPS || 10),
      timeUnit: "1s",
      preAllocatedVUs: Math.max(20, Number(__ENV.BENCHMARK_PEAK_RPS || 100)),
      maxVUs: Math.max(100, Number(__ENV.BENCHMARK_PEAK_RPS || 100) * 2),
      stages,
    },
  },
  thresholds: {},
};

if (__ENV.BENCHMARK_STRESS_PROFILE === "true") {
  const maximum5xxRatio = Number(
    __ENV.BENCHMARK_STRESS_MAX_5XX_RATIO || 0,
  );
  const maximum429Ratio = Number(
    __ENV.BENCHMARK_STRESS_MAX_429_RATIO || 0,
  );
  config.thresholds = {
    http_req_duration: [
      {
        threshold: `p(95)<${__ENV.BENCHMARK_STRESS_MAX_P95_MS}`,
        abortOnFail: true,
        delayAbortEval: "30s",
      },
      {
        threshold: `p(99)<${__ENV.BENCHMARK_STRESS_MAX_P99_MS}`,
        abortOnFail: true,
        delayAbortEval: "30s",
      },
    ],
    benchmark_backend_error_rate: [
      {
        threshold: `rate<${maximum5xxRatio === 0 ? 0.000001 : maximum5xxRatio}`,
        abortOnFail: true,
        delayAbortEval: "30s",
      },
    ],
    benchmark_rejection_rate: [
      {
        threshold: `rate<${maximum429Ratio === 0 ? 0.000001 : maximum429Ratio}`,
        abortOnFail: true,
        delayAbortEval: "30s",
      },
    ],
  };
}

export const options = config;

export default function () {
  const tenantCount = Math.max(1, Number(__ENV.BENCHMARK_TENANT_COUNT || 1));
  const hotspot = __ENV.BENCHMARK_HOTSPOT === "true";
  const paths = routePaths.map((path) => path.trim()).filter(Boolean);
  const routeIndex = __VU % paths.length;
  const tenantIndex = __VU % tenantCount;
  const selectedTenant = hotspot && __VU % 10 !== 0 ? 0 : tenantIndex;
  const tenantId = `benchmark-tenant-${selectedTenant}`;
  const routeId = __ENV.BENCHMARK_ROUTE_IMBALANCE === "true"
    ? (routeIndex === 0 ? "benchmark-expensive-route" : "benchmark-cheap-route")
    : `benchmark-route-${routeIndex}`;
  const path = paths[routeIndex] || "/";
  const baseUrl = __ENV.BENCHMARK_TARGET_URL.replace(/\/+$/, "");
  const headers = {
      "X-Tenant-ID": tenantId,
      "X-Benchmark-Route-ID": routeId,
      "X-Benchmark-Strategy": __ENV.BENCHMARK_STRATEGY || "unknown",
      "X-Benchmark-Config-Version": __ENV.BENCHMARK_CONFIG_VERSION || "unknown",
  };
  if (tenantTokens[selectedTenant]) {
    headers.Authorization = "Bearer " + tenantTokens[selectedTenant];
  }
  const response = http.get(`${baseUrl}${path}`, {
    headers,
    tags: {
      benchmark_strategy: __ENV.BENCHMARK_STRATEGY || "unknown",
      benchmark_scenario: __ENV.BENCHMARK_SCENARIO || "unknown",
    },
  });
  tenantDemand.add(1, { tenant_id: tenantId });
  if (
    response.headers["X-Benchmark-Active-Strategy"] !==
      (__ENV.BENCHMARK_STRATEGY || "unknown") ||
    response.headers["X-Benchmark-Active-Config-Version"] !==
      (__ENV.BENCHMARK_CONFIG_VERSION || "unknown")
  ) {
    strategyMismatches.add(1);
  }

  if (response.status === 429) {
    rateLimited.add(1);
    rejectionRate.add(true);
  } else {
    rejectionRate.add(false);
    accepted.add(1);
    acceptedLatency.add(response.timings.duration);
    backendLatency.add(response.timings.duration);
    tenantAccepted.add(1, { tenant_id: tenantId });
    if (response.status >= 500) {
      backendErrors.add(1);
      backendErrorRate.add(true);
    } else if (response.status >= 200 && response.status < 400) {
      backendErrorRate.add(false);
      successful.add(1);
    } else {
      backendErrorRate.add(false);
    }
  }
}
