from __future__ import annotations

import base64
import binascii
import json
import os
from datetime import UTC, datetime, time
from pathlib import Path
from queue import Queue
from threading import Thread
from typing import Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from agents.collector import CollectionOptions
from agents.evidence_rag import EvidenceRagAgent
from agents.structured import ClaudeBudget
from contracts import ArtifactStatus, EventBrief, Producer
from execution import ExecutionEvent
from orchestrator import EventPreflightOrchestrator, PipelineStopped
from res.corpus_collectors import EventCorpusCollector, UpdateCorpusCollector
from res.team_adapters import (
    EventJellyRedteamAdapter,
    EventJinbaeAuditAdapter,
    JellyRunner,
    JinbaeProbe,
    UpdateJellyRedteamAdapter,
    UpdateJinbaeAuditAdapter,
)
from update_review.collector import UpdateCollectionOptions
from update_review.contracts import UpdateBrief
from update_review.evidence import UpdateEvidenceAgent
from update_review.orchestrator import UpdateReviewOrchestrator

from .schemas import (
    HealthResponse,
    PipelineRunRequest,
    PipelineRunResponse,
    UpdatePipelineRunResponse,
    UpdateRunRequest,
    UpdateRunResult,
)

ROOT = Path(__file__).resolve().parents[2]
app = FastAPI(title="Game Changer API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("GAME_CHANGER_FRONTEND_ORIGIN", "http://localhost:3000")],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


_SAFE_VALIDATION_MESSAGES = frozenset(
    {
        "credential fields are not accepted",
        "details kind must match update_type",
        "cutoff_on must not be later than planned_on",
        "Dragunov fixture requires weapon_balance update_type",
        "live source requires steam_app_id or use_x",
        "live source requires period_start and period_end",
        "live source period requires timezone-aware datetimes",
        "live source period_start must be earlier than period_end",
        "live source period_end must not be later than cutoff_on",
        "import source requires imported_csv",
        "imported_csv must be UTF-8 text",
        "imported_csv is limited to 2 MB",
        "update details exceed the allowed size",
    }
)


@app.exception_handler(RequestValidationError)
async def request_validation_error(_request, exc: RequestValidationError) -> JSONResponse:
    """Return validation errors without echoing body values or unknown key names."""

    detail = []
    for error in exc.errors():
        message = str(error.get("msg", ""))
        prefix = "Value error, "
        if message.startswith(prefix) and message.removeprefix(prefix) in _SAFE_VALIDATION_MESSAGES:
            safe_message = message
        else:
            safe_message = "요청 형식이 올바르지 않습니다."
        detail.append(
            {
                "type": str(error.get("type", "value_error")),
                "loc": ["body"],
                "msg": safe_message,
            }
        )
    return JSONResponse(status_code=422, content={"detail": detail})


def _event(request: PipelineRunRequest, run_id: str) -> EventBrief:
    return EventBrief(
        run_id=run_id,
        status=ArtifactStatus.COMPLETE,
        producer=Producer.USER,
        input_refs=[],
        errors=[],
        game=request.game,
        event_name=request.event_name,
        goal=request.goal,
        starts_at=datetime.combine(request.starts_on, time.min, tzinfo=UTC),
        ends_at=datetime.combine(request.ends_on, time.min, tzinfo=UTC),
        target_users=request.target_users,
        participation_rule=request.participation_rule,
        repeat_rule=request.repeat_rule,
        rewards=request.rewards,
        currencies=request.currencies,
        probability_guarantee=request.probability_guarantee,
        monetization_policy=request.monetization_policy,
        expiration_policy=request.expiration_policy,
        cutoff_at=datetime.combine(request.cutoff_on, time.min, tzinfo=UTC),
    )


def _csv_bytes(value: str | None) -> bytes | None:
    if not value:
        return None
    try:
        decoded = base64.b64decode(value, validate=True)
        if len(decoded) > 2_000_000:
            raise HTTPException(status_code=422, detail="imported_csv is limited to 2 MB")
        return decoded
    except (ValueError, binascii.Error) as exc:
        raise HTTPException(status_code=422, detail="imported_csv must be base64 encoded") from exc


def _team_sidecars():
    budget = ClaudeBudget(max_requests=2)
    return JellyRunner(budget=budget), JinbaeProbe(budget=budget)


def _run(
    request: PipelineRunRequest,
    run_id: str,
    on_event: Callable[[ExecutionEvent], None] | None = None,
) -> dict:
    event = _event(request, run_id)
    options = CollectionOptions(
        use_fixture=request.source_mode == "fixture",
        fixture_case=request.fixture_case,
        imported_csv=_csv_bytes(request.imported_csv),
        steam_app_id=request.steam_app_id if request.source_mode == "live" else None,
        use_x=request.use_x if request.source_mode == "live" else False,
        x_query=request.x_query,
        x_estimated_total_cost_usd=request.x_estimated_total_cost_usd,
    )
    collector = (
        EventCorpusCollector(ROOT / ".data" / "corpus" / "pubg_steam.sqlite3")
        if request.source_mode == "corpus"
        else None
    )
    team_mode = request.source_mode == "corpus" and request.use_llm
    team = {}
    if team_mode:
        runner, probe = _team_sidecars()
        team = {
            "evidence_rag": EvidenceRagAgent(),
            "redteam": EventJellyRedteamAdapter(runner=runner, enabled=True),
            "audit": EventJinbaeAuditAdapter(probe=probe, enabled=True),
        }
    result = EventPreflightOrchestrator(
        use_llm=request.use_llm,
        llm_provider="claude" if team_mode else request.llm_provider,
        collector=collector,
        **team,
    ).run(
        event,
        options,
        on_event=on_event,
        log_path=ROOT / ".data" / "runs" / f"{run_id}.jsonl",
    )
    return {
        "brief": result.brief.model_dump(mode="json"),
        "feedback": result.feedback.model_dump(mode="json"),
        "evidence": result.evidence.model_dump(mode="json"),
        "risks": result.risks.model_dump(mode="json"),
        "validated": result.validated.model_dump(mode="json"),
        "events": [item.model_dump(mode="json") for item in result.events],
        "fallback_used": result.fallback_used,
        "analysis_incomplete": result.analysis_incomplete,
        "llm_provider": result.llm_provider,
        "llm_requested": result.llm_requested,
    }


def _update_csv_bytes(value: str | None) -> bytes | None:
    """Keep update import text separate from the event API's base64 helper."""

    if not value:
        return None
    try:
        encoded = value.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise HTTPException(
            status_code=422, detail="imported_csv must be UTF-8 text"
        ) from exc
    if len(encoded) > 2_000_000:
        raise HTTPException(status_code=422, detail="imported_csv is limited to 2 MB")
    return encoded


def _update_brief(request: UpdateRunRequest, run_id: str) -> UpdateBrief:
    return UpdateBrief(
        run_id=run_id,
        status=ArtifactStatus.COMPLETE,
        producer=Producer.USER,
        input_refs=[],
        errors=[],
        game=request.game,
        update_name=request.update_name,
        update_type=request.update_type,
        current_state=request.current_state,
        change_summary=request.change_summary,
        goal=request.goal,
        expected_benefits=request.expected_benefits,
        concerns=request.concerns,
        scope=request.scope,
        planned_at=datetime.combine(request.planned_on, time.min, tzinfo=UTC),
        cutoff_at=datetime.combine(request.cutoff_on, time.min, tzinfo=UTC),
        official_context_url=request.official_context_url,
        official_context=request.official_context,
        details=request.details,
    )


def _run_update(
    request: UpdateRunRequest,
    run_id: str,
    on_event: Callable[[ExecutionEvent], None] | None = None,
) -> UpdateRunResult:
    brief = _update_brief(request, run_id)
    options = UpdateCollectionOptions(
        use_fixture=request.source_mode == "fixture",
        fixture_case=request.fixture_case,
        imported_csv=(
            _update_csv_bytes(request.imported_csv)
            if request.source_mode == "import"
            else None
        ),
        steam_app_id=request.steam_app_id if request.source_mode == "live" else None,
        use_x=request.use_x if request.source_mode == "live" else False,
        x_query=request.x_query,
        period_start=request.period_start if request.source_mode == "live" else None,
        period_end=request.period_end if request.source_mode == "live" else None,
        x_estimated_total_cost_usd=request.x_estimated_total_cost_usd,
    )
    collector = (
        UpdateCorpusCollector(ROOT / ".data" / "corpus" / "pubg_steam.sqlite3")
        if request.source_mode == "corpus"
        else None
    )
    team = {}
    if request.source_mode == "corpus" and request.use_llm:
        runner, probe = _team_sidecars()
        team = {
            "evidence": UpdateEvidenceAgent(),
            "redteam": UpdateJellyRedteamAdapter(runner=runner, enabled=True),
            "audit": UpdateJinbaeAuditAdapter(probe=probe, enabled=True),
        }
    result = UpdateReviewOrchestrator(
        use_llm=request.use_llm,
        collector=collector,
        **team,
    ).run(
        brief,
        options,
        on_event=on_event,
        log_path=ROOT / ".data" / "runs" / f"{run_id}.jsonl",
    )
    return UpdateRunResult(
        brief=result.brief,
        feedback=result.feedback,
        evidence=result.evidence,
        impact=result.impact,
        validated=result.validated,
        events=result.events,
        fallback_used=result.fallback_used,
        analysis_incomplete=result.analysis_incomplete,
        llm_provider=result.llm_provider,
        llm_requested=result.llm_requested,
    )


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="game-changer-api")


@app.post("/api/runs", response_model=PipelineRunResponse)
def create_run(request: PipelineRunRequest) -> PipelineRunResponse:
    run_id = str(uuid4())
    try:
        result = _run(request, run_id)
    except (ValueError, PipelineStopped) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail="검토 실행 중 오류가 발생했습니다.") from exc
    return PipelineRunResponse(run_id=run_id, result=result)


@app.post("/api/runs/stream")
def stream_run(request: PipelineRunRequest) -> StreamingResponse:
    run_id = str(uuid4())
    messages: Queue[tuple[str, dict] | None] = Queue()

    def emit(event: ExecutionEvent) -> None:
        messages.put(("agent_event", {"event": event.model_dump(mode="json")}))

    def worker() -> None:
        try:
            messages.put(("started", {"run_id": run_id}))
            messages.put(("result", {"run_id": run_id, "result": _run(request, run_id, emit)}))
        except HTTPException as exc:
            messages.put(("error", {"detail": exc.detail, "status_code": exc.status_code}))
        except (ValueError, PipelineStopped) as exc:
            messages.put(("error", {"detail": str(exc), "status_code": 422}))
        except Exception:
            messages.put(("error", {"detail": "검토 실행 중 오류가 발생했습니다.", "status_code": 500}))
        finally:
            messages.put(None)

    Thread(target=worker, daemon=True).start()

    def events():
        while True:
            message = messages.get()
            if message is None:
                yield "event: done\ndata: {}\n\n"
                return
            name, payload = message
            yield f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/update-runs", response_model=UpdatePipelineRunResponse)
def create_update_run(request: UpdateRunRequest) -> UpdatePipelineRunResponse:
    run_id = str(uuid4())
    try:
        result = _run_update(request, run_id)
    except HTTPException:
        raise
    except (ValueError, PipelineStopped) as exc:
        raise HTTPException(
            status_code=422, detail="업데이트 요청을 안전하게 처리하지 못했습니다."
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500, detail="업데이트 점검 실행 중 오류가 발생했습니다."
        ) from exc
    return UpdatePipelineRunResponse(run_id=run_id, result=result)


@app.post("/api/update-runs/stream")
def stream_update_run(request: UpdateRunRequest) -> StreamingResponse:
    run_id = str(uuid4())
    messages: Queue[tuple[str, dict] | None] = Queue()

    def emit(event: ExecutionEvent) -> None:
        # The update orchestrator emits only contract-validated, code-owned
        # events.  Re-validating before serializing keeps the SSE boundary
        # limited to the same safe event envelope.
        safe_event = ExecutionEvent.model_validate(event)
        messages.put(("agent_event", {"event": safe_event.model_dump(mode="json")}))

    def worker() -> None:
        try:
            messages.put(("started", {"run_id": run_id}))
            result = _run_update(request, run_id, emit)
            messages.put(
                (
                    "result",
                    {"run_id": run_id, "result": result.model_dump(mode="json")},
                )
            )
        except HTTPException as exc:
            messages.put(
                (
                    "error",
                    {
                        "detail": "업데이트 요청을 안전하게 처리하지 못했습니다.",
                        "status_code": exc.status_code,
                    },
                )
            )
        except (ValueError, PipelineStopped):
            messages.put(
                (
                    "error",
                    {
                        "detail": "업데이트 요청을 안전하게 처리하지 못했습니다.",
                        "status_code": 422,
                    },
                )
            )
        except Exception:
            messages.put(
                (
                    "error",
                    {
                        "detail": "업데이트 점검 실행 중 오류가 발생했습니다.",
                        "status_code": 500,
                    },
                )
            )
        finally:
            messages.put(None)

    Thread(target=worker, daemon=True).start()

    def events():
        while True:
            message = messages.get()
            if message is None:
                yield "event: done\ndata: {}\n\n"
                return
            name, payload = message
            yield f"event: {name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
