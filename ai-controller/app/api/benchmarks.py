from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.api.telemetry import get_session, require_internal_api_key
from app.benchmarking.benchmark_repository import (
    BenchmarkRepository,
    map_result,
    map_run,
)
from app.benchmarking.benchmark_service import BenchmarkService
from app.benchmarking.schemas import (
    BenchmarkComparison,
    BenchmarkHistory,
    BenchmarkRequest,
    BenchmarkResult,
    BenchmarkRun,
    BenchmarkScenario,
    BenchmarkSubmission,
)

router = APIRouter(
    prefix="/api/v1/benchmarks",
    tags=["benchmarking"],
    dependencies=[Depends(require_internal_api_key)],
)


@router.post("/run", response_model=BenchmarkSubmission, status_code=202)
def submit_benchmark(
    payload: BenchmarkRequest,
    request: Request,
    session: Session = Depends(get_session),
) -> BenchmarkSubmission:
    try:
        return BenchmarkService(request.app.state.settings).submit(
            payload,
            session=session,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/compare", response_model=BenchmarkComparison)
def compare_benchmarks(
    request: Request,
    service_key: str = Query(min_length=1, max_length=100),
    scenario: BenchmarkScenario = Query(...),
    batch_id: UUID | None = None,
    repeats: int = Query(default=3, ge=3, le=100),
    session: Session = Depends(get_session),
) -> BenchmarkComparison:
    _check_service_key(request, service_key)
    if batch_id is None and repeats * 3 > 1000:
        raise HTTPException(status_code=422, detail="Too many benchmark repeats")
    try:
        return BenchmarkService(request.app.state.settings).compare(
            service_key=service_key,
            scenario=scenario,
            limit=repeats,
            batch_id=batch_id,
            session=session,
        )
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/history", response_model=BenchmarkHistory)
def benchmark_history(
    request: Request,
    service_key: str = Query(min_length=1, max_length=100),
    scenario: BenchmarkScenario | None = None,
    limit: int = Query(default=100, ge=1, le=1000),
    session: Session = Depends(get_session),
) -> BenchmarkHistory:
    _check_service_key(request, service_key)
    runs = BenchmarkRepository(session).history(
        service_key=service_key,
        scenario=scenario.value if scenario else None,
        limit=limit,
    )
    return BenchmarkHistory(runs=[map_run(item) for item in runs])


@router.get("/{run_id}/results", response_model=BenchmarkResult)
def benchmark_results(
    run_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> BenchmarkResult:
    repository = BenchmarkRepository(session)
    run = repository.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    _check_service_key(request, run.service_key)
    result = repository.result(run_id)
    if result is None:
        raise HTTPException(
            status_code=409,
            detail=f"Benchmark result is not available (status: {run.status})",
        )
    return map_result(result)


@router.get("/{run_id}", response_model=BenchmarkRun)
def benchmark_run(
    run_id: UUID,
    request: Request,
    session: Session = Depends(get_session),
) -> BenchmarkRun:
    run = BenchmarkRepository(session).get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Benchmark run not found")
    _check_service_key(request, run.service_key)
    return map_run(run)


def _check_service_key(request: Request, service_key: str) -> None:
    if service_key not in request.app.state.settings.service_keys:
        raise HTTPException(status_code=404, detail="Service not found")
