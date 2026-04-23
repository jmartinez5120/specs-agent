"""FastAPI app factory for the specs-agent backend.

The API is **stateless**: every request passes the data it needs. Persistent
state (plans, config, history) lives in the injected `Storage` layer.
This makes the API trivially horizontally scalable and gives identical
semantics across single-user (local TUI/web) and multi-user (Docker) deploys.

Routes:
  GET    /health                        → {"status": "ok"}
  POST   /specs/load                    → load a spec from URL or file path
  POST   /plans/generate                → generate a fresh plan from a spec
  POST   /plans/generate-or-merge       → generate + merge with saved plan
  POST   /plans/save                    → save a plan to storage
  GET    /plans/{spec_title}            → load saved plan for a spec
  POST   /plans/archive                 → archive a plan
  GET    /config                        → current config
  PUT    /config                        → update config
  GET    /history                       → list runs (query: spec_title, base_url)
  GET    /history/run                   → load a specific run
  POST   /reports/html                  → render HTML report
  WS     /ws/execute                    → live test execution stream
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Response,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from specs_agent.api import schemas as s
from specs_agent.api.converters import (
    config_to_dto,
    dto_to_config,
    dto_to_plan,
    dto_to_run_config,
    plan_to_dto,
)
from specs_agent.engine import Engine, FileStorage
from specs_agent.execution.runner import TestRunner
from specs_agent.models.results import Report
from specs_agent.parsing.extractor import extract_spec
from specs_agent.parsing.loader import SpecLoadError
from specs_agent.reporting.generator import generate_html_report


log = logging.getLogger("specs_agent.api")


# ---------------------------------------------------------------------- #
# Request DTOs that live with the app (not shared via schemas.py).
# ---------------------------------------------------------------------- #


class SearchRequest(BaseModel):
    """POST /search body.

    `kinds` defaults to None → all kinds. `limit` caps total ES hits
    across all kinds; the frontend typically slices each group to 5.
    """

    q: str = Field("", description="Free-text query. Empty → empty result.")
    kinds: list[str] | None = Field(
        default=None,
        description="Filter by kind (spec/endpoint/test_case/run). None = all.",
    )
    limit: int = Field(30, ge=1, le=200)


def _storage_is_mongo() -> bool:
    """Search + change-stream indexing only make sense with MongoStorage.

    File-backed storage has no change streams to tail, so the `/search`
    route 503s in that mode and the lifespan skips ES entirely.
    """
    return os.environ.get("SPECS_AGENT_STORAGE", "file").lower() == "mongo"


def create_app(engine: Engine | None = None) -> FastAPI:
    """Build a FastAPI app bound to the given engine.

    If no engine is provided, a default `Engine(FileStorage())` is used.
    Tests can inject a custom engine (e.g., with an isolated storage root).

    When `SPECS_AGENT_STORAGE=mongo`, a FastAPI lifespan hook connects to
    Elasticsearch, ensures the search index exists, runs a one-time
    backfill if empty, and starts a change-stream tailer. If ES is not
    reachable at startup the app fails fast — search is not optional in
    mongo mode. See `specs_agent.search` for the indexer.
    """
    engine = engine or Engine(FileStorage())

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        indexer = None
        if _storage_is_mongo():
            # Imports inside the lifespan so non-mongo deploys don't pay
            # the cost of importing motor/elasticsearch at module load.
            from specs_agent.search.client import get_client, close_client, ping
            from specs_agent.search.indexer import Indexer

            if not await ping():
                # Fail fast — the docker-compose setup should always make
                # ES reachable in mongo mode. Silent degradation would
                # mean "search always returns empty" in prod, which is
                # worse than refusing to start.
                raise RuntimeError(
                    "Elasticsearch unreachable at "
                    f"{os.environ.get('ELASTICSEARCH_URL', 'http://localhost:9200')}. "
                    "Search requires ES in mongo-storage mode."
                )

            mongo_url = os.environ.get(
                "SPECS_AGENT_MONGO_URL", "mongodb://localhost:27017"
            )
            mongo_db = os.environ.get("SPECS_AGENT_MONGO_DB", "specs_agent")
            indexer = Indexer(
                mongo_url=mongo_url,
                mongo_db=mongo_db,
                es_client=get_client(),
            )
            try:
                await indexer.start()
                app.state.search_indexer = indexer
                app.state.search_enabled = True
            except Exception:
                log.exception("failed to start search indexer")
                raise
        else:
            app.state.search_indexer = None
            app.state.search_enabled = False

        try:
            yield
        finally:
            if indexer is not None:
                try:
                    await indexer.stop()
                except Exception:
                    log.exception("error during indexer shutdown")
            if _storage_is_mongo():
                from specs_agent.search.client import close_client
                await close_client()

    app = FastAPI(
        title="specs-agent API",
        version="0.1.0",
        description="Backend API for the specs-agent testing tool. "
                    "Wraps the core engine over HTTP + WebSocket.",
        lifespan=lifespan,
    )

    # CORS — the Web UI will likely live on a different port in dev.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Expose the engine on app.state so routes (and tests) can reach it.
    app.state.engine = engine

    def get_engine() -> Engine:
        return app.state.engine

    # ------------------------------------------------------------------ #
    # Health
    # ------------------------------------------------------------------ #

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "specs-agent-api"}

    # ------------------------------------------------------------------ #
    # Try It proxy — fires an HTTP request server-side so the Web UI's
    # "Try It" modal isn't blocked by the browser's CORS policy and can
    # reach hosts only the backend can resolve (e.g. host.docker.internal,
    # internal k8s services, etc.).
    # ------------------------------------------------------------------ #

    @app.post("/proxy-request")
    async def proxy_request(payload: dict) -> dict:
        import time
        import httpx
        from specs_agent.net import rewrite_localhost_for_docker

        method = str(payload.get("method", "GET")).upper()
        url = rewrite_localhost_for_docker(str(payload.get("url", "")))
        headers = payload.get("headers") or {}
        body = payload.get("body")
        timeout = float(payload.get("timeout_seconds") or 30)
        verify_ssl = bool(payload.get("verify_ssl", True))

        if not url:
            return {"error": "url is required"}

        req_kwargs: dict = {"method": method, "url": url, "headers": headers}
        if body is not None and method not in ("GET", "HEAD"):
            if isinstance(body, (dict, list)):
                req_kwargs["json"] = body
                headers.setdefault("content-type", "application/json")
            else:
                req_kwargs["content"] = str(body)

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(verify=verify_ssl, timeout=timeout, follow_redirects=True) as client:
                resp = await client.request(**req_kwargs)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            text = resp.text
            try:
                parsed_body: object = resp.json()
            except Exception:
                parsed_body = text
            return {
                "ok": True,
                "status_code": resp.status_code,
                "reason_phrase": resp.reason_phrase,
                "elapsed_ms": elapsed_ms,
                "headers": dict(resp.headers),
                "body": parsed_body,
                "body_text": text,
                "final_url": str(resp.url),
            }
        except httpx.HTTPError as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": elapsed_ms,
            }
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            return {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
                "elapsed_ms": elapsed_ms,
            }

    # ------------------------------------------------------------------ #
    # Specs
    # ------------------------------------------------------------------ #

    @app.post("/specs/load")
    async def load_spec(req: s.LoadSpecRequest, eng: Engine = Depends(get_engine)) -> dict:
        effective_source = rewrite_localhost_for_docker(req.source)
        try:
            result = eng.load_spec_from_source(effective_source)
        except SpecLoadError as exc:
            raise HTTPException(
                status_code=400,
                detail=_load_error_with_hint(exc, req.source, effective_source),
            )
        # Auto-save the spec for the spec browser
        try:
            eng.save_spec(
                title=result.spec.title,
                source=req.source,
                source_type=result.source_type,
                raw_spec=result.spec.raw_spec,
            )
        except Exception:
            pass  # best-effort — don't fail the load if save fails

        spec_dict = jsonable_encoder(asdict(result.spec))

        return {
            "spec": spec_dict,
            "source": req.source,
            "source_type": result.source_type,
            "warnings": result.warnings,
        }

    @app.get("/specs/saved")
    async def list_saved_specs(
        limit: int = Query(20, ge=1, le=100),
        eng: Engine = Depends(get_engine),
    ) -> list[dict]:
        return eng.list_saved_specs(limit)

    @app.get("/specs/saved/{spec_id}")
    async def load_saved_spec(spec_id: str, eng: Engine = Depends(get_engine)) -> dict:
        data = eng.load_saved_spec(spec_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Spec '{spec_id}' not found")
        return data

    @app.delete("/specs/saved/{spec_id}")
    async def delete_saved_spec(spec_id: str, eng: Engine = Depends(get_engine)) -> dict:
        deleted = eng.delete_saved_spec(spec_id)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"Spec '{spec_id}' not found")
        return {"deleted": spec_id}

    # ------------------------------------------------------------------ #
    # Plans
    # ------------------------------------------------------------------ #

    @app.post("/plans/generate")
    async def generate_plan(req: s.GeneratePlanRequest, eng: Engine = Depends(get_engine)) -> s.TestPlanDTO:
        try:
            spec = extract_spec(req.spec.raw_spec, source_url=req.spec.source)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid spec: {exc}")
        plan = eng.generate_plan(spec)
        # Auto-save so we don't have to regenerate next time
        try:
            eng.save_plan(plan)
        except Exception:
            pass
        return plan_to_dto(plan)

    @app.post("/plans/generate-or-merge")
    async def generate_or_merge_plan(
        req: s.GeneratePlanRequest, eng: Engine = Depends(get_engine),
    ) -> dict:
        try:
            spec = extract_spec(req.spec.raw_spec, source_url=req.spec.source)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid spec: {exc}")
        plan, merge = eng.generate_or_merge_plan(spec)
        # Auto-save
        try:
            eng.save_plan(plan)
        except Exception:
            pass
        return {
            "plan": plan_to_dto(plan).model_dump(),
            "merge": None if merge is None else {
                "kept": merge.kept,
                "new": merge.new,
                "removed": merge.removed,
            },
        }

    @app.post("/plans/save")
    async def save_plan(req: s.SavePlanRequest, eng: Engine = Depends(get_engine)) -> dict:
        plan = dto_to_plan(req.plan)
        path = eng.save_plan(plan)
        return {"path": path}

    @app.get("/plans/{spec_title}")
    async def load_saved_plan(spec_title: str, eng: Engine = Depends(get_engine)) -> s.TestPlanDTO:
        plan = eng.load_saved_plan(spec_title)
        if plan is None:
            raise HTTPException(status_code=404, detail=f"No saved plan for '{spec_title}'")
        return plan_to_dto(plan)

    @app.post("/plans/archive")
    async def archive_plan(req: s.SavePlanRequest, eng: Engine = Depends(get_engine)) -> dict:
        plan = dto_to_plan(req.plan)
        path = eng.archive_plan(plan)
        return {"path": path}

    # ------------------------------------------------------------------ #
    # Search — Elasticsearch-backed, grouped-by-kind results.
    #
    # The index is populated by a change-stream tailer (see
    # `specs_agent.search.indexer`) that mirrors Mongo writes into ES in
    # near real-time. All writes go through Mongo; ES is read-only from
    # the API's point of view.
    #
    # Only available in mongo-storage mode — file storage returns 503
    # because there are no change streams to drive the index.
    # ------------------------------------------------------------------ #

    @app.post("/search")
    async def search_route(req: SearchRequest) -> dict:
        if not getattr(app.state, "search_enabled", False):
            raise HTTPException(
                status_code=503,
                detail=(
                    "search requires mongo storage "
                    "(set SPECS_AGENT_STORAGE=mongo and restart)"
                ),
            )
        from specs_agent.search.service import result_to_dict, search
        result = await search(
            req.q,
            kinds=req.kinds,
            limit=req.limit,
        )
        return result_to_dict(result)

    # ------------------------------------------------------------------ #
    # Config
    # ------------------------------------------------------------------ #

    @app.get("/config")
    async def get_config(eng: Engine = Depends(get_engine)) -> s.AppConfigDTO:
        return config_to_dto(eng.load_config())

    @app.put("/config")
    async def put_config(dto: s.AppConfigDTO, eng: Engine = Depends(get_engine)) -> Response:
        eng.save_config(dto_to_config(dto))
        return Response(status_code=204)

    # ------------------------------------------------------------------ #
    # History
    # ------------------------------------------------------------------ #

    @app.get("/history")
    async def list_history(
        spec_title: str = Query(...),
        base_url: str = Query(...),
        limit: int = Query(20, ge=1, le=100),
        eng: Engine = Depends(get_engine),
    ) -> list[dict]:
        return eng.list_history(spec_title, base_url, limit)

    @app.get("/history/run")
    async def load_history_run(
        spec_title: str = Query(...),
        base_url: str = Query(...),
        filename: str = Query(...),
        eng: Engine = Depends(get_engine),
    ) -> dict:
        report = eng.load_history_run(spec_title, base_url, filename)
        if report is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return _serialize_report(report)

    # ------------------------------------------------------------------ #
    # Reports
    # ------------------------------------------------------------------ #

    @app.post("/reports/html", response_class=HTMLResponse)
    async def render_report(req: s.RenderReportRequest) -> HTMLResponse:
        try:
            report = _dict_to_report(req.report)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"Invalid report payload: {exc}")

        if req.output_path:
            path = generate_html_report(report, req.output_path)
            html = Path(path).read_text()
            return HTMLResponse(content=html, headers={"X-Output-Path": path})

        # Inline render to a tempfile → read → return
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
            path = generate_html_report(report, tmp.name)
        html = Path(path).read_text()
        Path(path).unlink(missing_ok=True)
        return HTMLResponse(content=html)

    # ------------------------------------------------------------------ #
    # AI
    # ------------------------------------------------------------------ #

    @app.get("/ai/status")
    async def ai_status(eng: Engine = Depends(get_engine)) -> dict:
        config = eng.load_config()
        if not config.ai_enabled:
            return {"enabled": False, "available": False, "model_loaded": False}
        try:
            from specs_agent.ai.generator import AIGenerator
            gen = AIGenerator(
                model_path=config.ai_model_path,
                model_size=config.ai_model_size,
                n_ctx=config.ai_n_ctx,
                n_gpu_layers=config.ai_n_gpu_layers,
                cache_dir=config.ai_cache_dir,
                backend=config.ai_backend,
                http_base_url=config.ai_http_base_url,
                http_model=config.ai_http_model,
                http_api_key=config.ai_http_api_key,
            )
            status = gen.status()
            status["enabled"] = True
            status["available"] = gen.is_available()
            return status
        except ImportError:
            return {"enabled": True, "available": False, "error": "llama-cpp-python not installed"}

    @app.post("/ai/cache/clear")
    async def ai_cache_clear(eng: Engine = Depends(get_engine)) -> dict:
        config = eng.load_config()
        from specs_agent.ai.cache import AICache
        cache = AICache(config.ai_cache_dir)
        removed = cache.clear_all()
        return {"cleared": removed}

    @app.get("/ai/presets")
    async def ai_presets() -> list[dict]:
        from specs_agent.ai.models import get_preset_info
        return get_preset_info()

    # ------------------------------------------------------------------ #
    # WebSocket: live plan generation (with progress)
    # ------------------------------------------------------------------ #

    @app.websocket("/ws/generate")
    async def generate_ws(websocket: WebSocket) -> None:
        """Stream plan generation progress over WebSocket.

        All blocking work (parsing, AI inference) runs in a thread executor
        so the event loop stays free to flush WebSocket frames immediately.
        """
        await websocket.accept()
        try:
            raw = await websocket.receive_text()
            data = json.loads(raw)
        except Exception as exc:
            await websocket.send_json({"event": "error", "message": f"Invalid request: {exc}"})
            await websocket.close()
            return

        eng = app.state.engine
        loop = asyncio.get_running_loop()

        async def send(event: dict) -> None:
            try:
                await websocket.send_json(event)
                # Yield to let the frame flush before the next blocking call
                await asyncio.sleep(0)
            except Exception:
                pass

        try:
            await send({"event": "step", "step": "Parsing spec...", "progress": 2})

            raw_spec = data.get("raw_spec", {})
            source = data.get("source", "")
            # Regenerate options (default to current behavior when omitted).
            include_happy = bool(data.get("include_happy", True))
            include_sad = bool(data.get("include_sad", True))
            include_ai = bool(data.get("include_ai", False))
            # Run parsing in thread (prance can be slow on large specs)
            spec = await loop.run_in_executor(
                None, lambda: extract_spec(raw_spec, source_url=source)
            )
            total_endpoints = len(spec.endpoints)

            await send({"event": "step", "step": f"Found {total_endpoints} endpoints", "progress": 5})

            # Load config for AI settings
            config = await loop.run_in_executor(None, eng.load_config)
            ai_gen = None
            model_name = ""
            # UI toggle wins: include_ai overrides persisted config.ai_enabled.
            ai_requested = include_ai if "include_ai" in data else config.ai_enabled
            if ai_requested:
                await send({"event": "step", "step": "Initializing AI model...", "progress": 8})
                try:
                    from specs_agent.ai.generator import AIGenerator
                    from specs_agent.ai.models import PRESETS

                    ai_gen = AIGenerator(
                        model_path=config.ai_model_path,
                        model_size=config.ai_model_size,
                        n_ctx=config.ai_n_ctx,
                        n_gpu_layers=config.ai_n_gpu_layers,
                        cache_dir=config.ai_cache_dir,
                        backend=config.ai_backend,
                        http_base_url=config.ai_http_base_url,
                        http_model=config.ai_http_model,
                        http_api_key=config.ai_http_api_key,
                    )

                    # Resolve model name for display
                    if config.ai_backend == "http" or (config.ai_backend == "auto" and config.ai_http_model):
                        model_name = f"{config.ai_http_model} (via {config.ai_http_base_url or 'HTTP API'}) · GPU"
                    else:
                        preset = PRESETS.get(config.ai_model_size)
                        if preset:
                            model_name = f"{preset.description}"
                        elif ai_gen.resolved_model_path:
                            model_name = ai_gen.resolved_model_path.name
                        else:
                            model_name = config.ai_model_size

                    if not ai_gen.is_available():
                        await send({"event": "step", "step": "AI model not available — using Faker only", "progress": 10})
                        ai_gen = None
                    else:
                        await send({"event": "step", "step": f"AI ready: {model_name}", "progress": 10, "model": model_name})
                except Exception as exc:
                    await send({"event": "step", "step": f"AI init failed: {exc} — using Faker only", "progress": 10})
                    ai_gen = None

            from specs_agent.parsing.plan_generator import (
                _generate_cases_for_endpoint,
                _generate_ai_scenarios,
            )
            from specs_agent.models.plan import TestPlan
            from datetime import datetime, timezone

            plan = TestPlan(
                name=f"{spec.title} Test Plan",
                spec_title=spec.title,
                base_url=spec.base_url,
                created_at=datetime.now(timezone.utc).isoformat(),
            )

            # Phase 1: Rule-based generation (12–52% of progress)
            for i, endpoint in enumerate(spec.endpoints):
                pct = 12 + int((i / max(total_endpoints, 1)) * 40)
                await send({
                    "event": "step",
                    "step": f"Generating: {endpoint.method.value} {endpoint.path}",
                    "progress": pct,
                    "detail": f"Rule-based · {i + 1}/{total_endpoints}",
                })

                # Run blocking case generation in thread
                cases = await loop.run_in_executor(
                    None, lambda ep=endpoint: _generate_cases_for_endpoint(ep, ai=ai_gen)
                )
                plan.test_cases.extend(cases)

                if endpoint.performance_sla:
                    key = f"{endpoint.method.value} {endpoint.path}"
                    sla = endpoint.performance_sla
                    plan.performance_slas[key] = {
                        "p95_ms": sla.latency_p95_ms,
                        "p99_ms": sla.latency_p99_ms,
                        "throughput_rps": sla.throughput_rps,
                        "timeout_ms": sla.timeout_ms,
                    }

            rule_based_count = len(plan.test_cases)
            await send({
                "event": "step",
                "step": f"Rule-based complete: {rule_based_count} test cases",
                "progress": 52,
                "detail": f"{rule_based_count} cases from {total_endpoints} endpoints",
            })

            # Phase 2: AI scenario generation (55–95% of progress)
            if ai_gen:
                await send({
                    "event": "step",
                    "step": f"AI scenario generation starting · {model_name}",
                    "progress": 55,
                    "model": model_name,
                })
                total_dropped = 0
                for i, endpoint in enumerate(spec.endpoints):
                    pct = 55 + int((i / max(total_endpoints, 1)) * 40)
                    await send({
                        "event": "step",
                        "step": f"AI: {endpoint.method.value} {endpoint.path}",
                        "progress": pct,
                        "detail": f"AI scenarios · {i + 1}/{total_endpoints} · {model_name}",
                    })

                    # Run blocking AI inference in thread. The `on_phase`
                    # hook is called from the worker thread after the LLM
                    # returns, so we schedule the progress send back onto
                    # the event loop.
                    def _phase_hook(phase: str, raw_count: int, ep=endpoint, pct=pct) -> None:
                        if phase == "validating":
                            asyncio.run_coroutine_threadsafe(
                                send({
                                    "event": "step",
                                    "step": f"AI: {ep.method.value} {ep.path} — validating {raw_count} scenarios",
                                    "progress": pct,
                                    "detail": "Checking status codes, param names, body/response sanity",
                                }),
                                loop,
                            )

                    ai_cases, drop_reasons = await loop.run_in_executor(
                        None,
                        lambda ep=endpoint, cb=_phase_hook: _generate_ai_scenarios(ep, ai_gen, on_phase=cb),
                    )
                    plan.test_cases.extend(ai_cases)
                    total_dropped += len(drop_reasons)
                    if drop_reasons:
                        await send({
                            "event": "step",
                            "step": f"AI: {endpoint.method.value} {endpoint.path} — dropped {len(drop_reasons)}",
                            "progress": pct,
                            "detail": "; ".join(drop_reasons)[:200],
                        })

                ai_count = len(plan.test_cases) - rule_based_count
                summary = f"AI complete: {ai_count} additional scenarios"
                if total_dropped:
                    summary += f" · {total_dropped} dropped (validation)"
                summary += f" · {model_name}"
                await send({
                    "event": "step",
                    "step": summary,
                    "progress": 95,
                })

            # Filter cases by the happy/sad toggles from the UI before merging.
            if not include_happy or not include_sad:
                plan.test_cases = [
                    tc for tc in plan.test_cases
                    if (tc.test_type == "happy" and include_happy)
                    or (tc.test_type == "sad" and include_sad)
                ]

            # Phase 3: Merge with saved plan + save
            await send({"event": "step", "step": "Merging with saved plan...", "progress": 96})
            saved = await loop.run_in_executor(
                None, lambda: eng.load_saved_plan(spec.title)
            )
            merge_result = None
            if saved:
                mr = eng.merge_plans(plan, saved)
                plan = mr.plan
                merge_result = {"kept": mr.kept, "new": mr.new, "removed": mr.removed}

            await send({"event": "step", "step": "Saving plan...", "progress": 98})
            try:
                await loop.run_in_executor(None, lambda: eng.save_plan(plan))
            except Exception:
                pass

            await send({"event": "step", "step": "Done!", "progress": 100})

            plan_dto = plan_to_dto(plan).model_dump()
            await send({
                "event": "complete",
                "plan": plan_dto,
                "merge": merge_result,
            })

        except Exception as exc:
            await send({"event": "error", "message": str(exc)})
        finally:
            try:
                await websocket.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # WebSocket: live test execution
    # ------------------------------------------------------------------ #

    @app.websocket("/ws/execute")
    async def execute_ws(websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            raw = await websocket.receive_text()
            payload = s.ExecuteRequest.model_validate_json(raw)
        except Exception as exc:
            await websocket.send_json({"event": "error", "message": f"Invalid request: {exc}"})
            await websocket.close()
            return

        plan = dto_to_plan(payload.plan)
        config = dto_to_run_config(payload.config)
        runner = TestRunner(plan, config)

        # Direct-send approach: callbacks send WebSocket frames immediately
        # via an async helper, ensuring real-time delivery without queue lag.
        _ws_open = True

        async def send_event(event: dict) -> None:
            if not _ws_open:
                return
            try:
                await websocket.send_json(event)
            except (WebSocketDisconnect, RuntimeError):
                pass

        def enqueue(event: dict) -> None:
            """Schedule an event to be sent on the next event loop tick."""
            if not _ws_open:
                return
            asyncio.ensure_future(send_event(event))

        try:
            async def run_task():
                report = await runner.run(
                    on_result=lambda r: enqueue({
                        "event": "result",
                        "result": jsonable_encoder(asdict(r)),
                    }),
                    on_progress=lambda i, t: enqueue({
                        "event": "progress",
                        "completed": i,
                        "total": t,
                    }),
                    on_perf_update=lambda stats: enqueue({
                        "event": "perf",
                        "stats": jsonable_encoder(stats),
                    }),
                    on_phase=lambda p: enqueue({"event": "phase", "phase": p}),
                )
                return report

            # Watch for client cancel messages in parallel
            async def cancel_watcher() -> None:
                while True:
                    try:
                        msg = await websocket.receive_text()
                    except WebSocketDisconnect:
                        runner.cancel()
                        return
                    try:
                        data = json.loads(msg)
                    except Exception:
                        continue
                    if data.get("action") == "cancel":
                        runner.cancel()
                        return

            run_fut = asyncio.create_task(run_task())
            watch_fut = asyncio.create_task(cancel_watcher())

            done, pending = await asyncio.wait(
                [run_fut, watch_fut],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for t in pending:
                t.cancel()

            if run_fut in done:
                report = run_fut.result()
                # Save to history FIRST (before WebSocket might close)
                try:
                    app.state.engine.save_run_to_history(report)
                except Exception:
                    pass
                # Send complete event directly to ensure delivery
                await send_event({
                    "event": "complete",
                    "report": _serialize_report(report),
                })

            # Small delay for any in-flight sends to complete
            await asyncio.sleep(0.1)

        except WebSocketDisconnect:
            runner.cancel()
        finally:
            _ws_open = False
            try:
                await websocket.close()
            except Exception:
                pass

    return app


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _dict_to_report(data: dict) -> Report:
    """Best-effort reconstruction of a Report dataclass from a JSON dict."""
    from specs_agent.history.storage import _dict_to_report as hist_dict_to_report
    return hist_dict_to_report(data)


# ---------------------------------------------------------------------- #
# Docker-aware source rewriting
# ---------------------------------------------------------------------- #


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _running_in_docker() -> bool:
    """True if the API process is running inside a Docker container.

    We honour an explicit opt-in env var first (so CI can force behavior),
    then fall back to the canonical `/.dockerenv` marker that Docker Engine
    creates on every container.
    """
    flag = os.environ.get("SPECS_AGENT_IN_DOCKER", "").strip().lower()
    if flag in ("1", "true", "yes"):
        return True
    if flag in ("0", "false", "no"):
        return False
    return Path("/.dockerenv").exists()


def rewrite_localhost_for_docker(source: str) -> str:
    """Transparently swap `localhost` / `127.0.0.1` for `host.docker.internal`
    when the API is running inside a container.

    Why: users running another API on their host (e.g. on :8080) naturally
    type `http://localhost:8080/...` into the Web UI. That URL is then
    fetched **from inside the API container**, where `localhost` means
    the container itself — not the host. Docker Desktop provides a magic
    DNS name `host.docker.internal` that resolves to the host; on Linux
    the docker-compose.yml adds an `extra_hosts` entry so the same name
    works there too.

    This is a no-op outside of Docker, and a no-op for file paths or
    non-loopback URLs.
    """
    if not source or not isinstance(source, str):
        return source
    if not source.startswith(("http://", "https://")):
        return source
    if not _running_in_docker():
        return source

    parts = urlsplit(source)
    host = (parts.hostname or "").lower()
    if host not in _LOOPBACK_HOSTS:
        return source

    # Preserve user:pass and port when reconstructing
    netloc = "host.docker.internal"
    if parts.port is not None:
        netloc += f":{parts.port}"
    if parts.username:
        userinfo = parts.username
        if parts.password:
            userinfo += f":{parts.password}"
        netloc = f"{userinfo}@{netloc}"

    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


def _load_error_with_hint(
    exc: Exception, original: str, effective: str,
) -> str:
    """Wrap a spec-load failure with a helpful hint about the network.

    If the rewrite already happened (effective != original) and still
    failed, the user probably needs to make sure the host service is
    actually reachable on the port they typed. If the rewrite did NOT
    happen (same source) and we're in Docker with a loopback URL that
    somehow slipped through, suggest host.docker.internal explicitly.
    """
    base = str(exc)
    if effective != original:
        return (
            f"{base}\n\n"
            f"(auto-rewrote {original} → {effective} because the API "
            f"runs inside Docker; make sure your host service is reachable "
            f"from the container — e.g. bind it to 0.0.0.0:PORT, not 127.0.0.1:PORT)"
        )
    return base


def _serialize_report(report: Report) -> dict:
    """Serialize a Report including its computed properties.

    `dataclasses.asdict()` drops @property fields, but UIs need counts
    and pass rates — so we splice them in alongside the raw fields.
    """
    data = jsonable_encoder(asdict(report))
    data["total_tests"] = report.total_tests
    data["passed_tests"] = report.passed_tests
    data["failed_tests"] = report.failed_tests
    data["error_tests"] = report.error_tests
    data["pass_rate"] = report.pass_rate
    return data
