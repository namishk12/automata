"""FastAPI application for Automata."""

from __future__ import annotations

import asyncio
import json
import os
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse

from .browser import BrowserService, ExecutionManager, artifacts_dir, sessions_dir
from .db import Database
from .demo_site import router as demo_router
from .exports import json_export, python_export
from .model_adapter import ModelAdapter, ModelError
from .planner import generate_macro
from .schemas import Macro, ModelSettingsUpdate, PlanRequest, RepairRequest, RunRequest, utc_now
from .storage import Storage


database = Database()
database.initialize()
storage = Storage(database)
storage.recover_interrupted_runs()
browser_service = BrowserService()
execution = ExecutionManager(storage, browser_service)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await browser_service.close()
    database.close()


app = FastAPI(title="Automata", version="0.1.0", lifespan=lifespan)
allowed_origins = [origin.strip() for origin in os.getenv("AUTOMATA_ALLOWED_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)
app.include_router(demo_router)


@app.get("/api/health")
async def health() -> dict[str, Any]:
    settings = ModelAdapter.from_storage(storage).public_settings()
    return {"ok": True, "service": "automata", "model": settings.model, "model_configured": settings.api_key_configured}


@app.get("/api/settings/model")
async def get_model_settings() -> dict[str, Any]:
    return ModelAdapter.from_storage(storage).public_settings().model_dump()


@app.put("/api/settings/model")
async def update_model_settings(update: ModelSettingsUpdate) -> dict[str, Any]:
    ModelAdapter.update_storage(storage, update)
    return ModelAdapter.from_storage(storage).public_settings().model_dump()


@app.post("/api/settings/model/test")
async def test_model_connection() -> dict[str, Any]:
    adapter = ModelAdapter.from_storage(storage)
    if not adapter.settings.api_key_configured and adapter.settings.endpoint.startswith("https://api.openai.com"):
        raise HTTPException(status_code=400, detail="Configure AUTOMATA_MODEL_API_KEY or save a key in Settings first.")
    try:
        return await adapter.test_connection()
    except ModelError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/plans/generate")
async def create_plan(request: PlanRequest) -> dict[str, Any]:
    macro, meta = await generate_macro(request, storage)
    return {"macro": macro.model_dump(mode="json"), "meta": meta}


@app.get("/api/macros")
async def list_macros(q: str = Query(default="")) -> list[dict[str, Any]]:
    return [macro.model_dump(mode="json") for macro in storage.list_macros(q)]


@app.post("/api/macros")
async def save_macro(macro: Macro) -> dict[str, Any]:
    saved = storage.save_macro(macro)
    return saved.model_dump(mode="json")


@app.get("/api/macros/{macro_id}")
async def get_macro(macro_id: str) -> dict[str, Any]:
    macro = storage.get_macro(macro_id)
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    return macro.model_dump(mode="json")


@app.post("/api/macros/{macro_id}/duplicate")
async def duplicate_macro(macro_id: str) -> dict[str, Any]:
    macro = storage.get_macro(macro_id)
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    duplicate = macro.model_copy(update={"id": None, "name": f"{macro.name} copy", "created_at": None, "modified_at": None})
    return storage.save_macro(duplicate).model_dump(mode="json")


@app.delete("/api/macros/{macro_id}")
async def delete_macro(macro_id: str) -> dict[str, bool]:
    if not storage.delete_macro(macro_id):
        raise HTTPException(status_code=404, detail="Macro not found")
    return {"deleted": True}


def _required_parameter_error(macro: Macro, variables: dict[str, Any]) -> str | None:
    defaults = {parameter.name: parameter.default for parameter in macro.parameters if parameter.default is not None}
    merged = {**defaults, **variables}
    missing = [parameter.name for parameter in macro.parameters if parameter.required and merged.get(parameter.name) in (None, "")]
    return ", ".join(missing) if missing else None


@app.post("/api/runs")
async def start_run(request: RunRequest) -> dict[str, Any]:
    macro = storage.get_macro(request.macro_id) if request.macro_id else request.macro
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    missing = _required_parameter_error(macro, request.variables)
    if missing:
        raise HTTPException(status_code=422, detail=f"Missing required parameters: {missing}")
    if execution.active_run_id and execution._is_active(execution.active_run_id):
        raise HTTPException(status_code=409, detail="Another browser run is already active.")
    run_id = str(uuid.uuid4())
    record = storage.create_run(
        run_id,
        macro.id,
        {
            "macro": macro.model_dump(mode="json"),
            "variables": request.variables,
            "options": {
                "session_name": request.session_name,
                "ai_repair": request.ai_repair,
                "repair_attempts": request.repair_attempts,
                "pause_between_steps": request.pause_between_steps,
            },
        },
        status="Planning",
    )
    storage.append_event(run_id, "status", {"status": "Planning", "message": "Run queued."})
    try:
        await execution.start_run(
            run_id,
            macro,
            request.variables,
            {
                "session_name": request.session_name,
                "ai_repair": request.ai_repair,
                "repair_attempts": request.repair_attempts,
                "pause_between_steps": request.pause_between_steps,
            },
        )
    except Exception as exc:
        storage.update_run(run_id, status="Failed", finished_at=utc_now(), error={"kind": type(exc).__name__, "message": str(exc)})
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"id": run_id, "status": record["status"], "macro": macro.model_dump(mode="json")}


@app.get("/api/runs")
async def list_runs(limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
    return storage.list_runs(limit)


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@app.post("/api/runs/{run_id}/pause")
async def pause_run(run_id: str) -> dict[str, Any]:
    try:
        return await execution.pause(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str) -> dict[str, Any]:
    try:
        return await execution.resume(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str) -> dict[str, Any]:
    try:
        return await execution.stop(run_id)
    except KeyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/repair")
async def repair_run(run_id: str, request: RepairRequest) -> dict[str, Any]:
    run = storage.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    if run.get("status") not in {"Failed", "Paused"}:
        raise HTTPException(status_code=409, detail="Repair is available after a failed or paused run.")
    if request.apply:
        raise HTTPException(status_code=400, detail="Repairs are applied automatically only when AI-assisted repair is enabled before the run.")
    return {"run_id": run_id, "repairs": run.get("repairs", []), "message": "Enable AI-assisted repair on the next run to allow bounded proposals."}


@app.get("/api/runs/{run_id}/events")
async def run_events(run_id: str, request: Request) -> StreamingResponse:
    if not storage.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    queue = await execution.subscribe(run_id)
    initial = storage.list_events(run_id)

    async def stream():
        try:
            for event in initial:
                yield f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                if event.get("type") == "done":
                    return
            while True:
                if await request.is_disconnected():
                    return
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=15)
                    yield f"id: {event['id']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                    if event.get("type") == "done":
                        return
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            execution.unsubscribe(run_id, queue)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


def _safe_artifact(run_id: str, filename: str | None = None) -> Path:
    root = artifacts_dir(run_id).resolve()
    if filename:
        candidate = (root / filename).resolve()
        if candidate.parent != root:
            raise HTTPException(status_code=400, detail="Invalid artifact name")
    else:
        candidates = sorted(root.glob("*.png"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not candidates:
            raise HTTPException(status_code=404, detail="No screenshot captured yet")
        candidate = candidates[0]
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="Artifact not found")
    return candidate


@app.get("/api/runs/{run_id}/screenshot")
async def run_screenshot(run_id: str, name: str | None = None) -> FileResponse:
    if not storage.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    return FileResponse(_safe_artifact(run_id, name), media_type="image/png")


@app.get("/api/runs/{run_id}/artifacts/{filename}")
async def run_artifact(run_id: str, filename: str) -> FileResponse:
    if not storage.get_run(run_id):
        raise HTTPException(status_code=404, detail="Run not found")
    path = _safe_artifact(run_id, filename)
    media_type = "text/csv" if path.suffix.lower() == ".csv" else "application/octet-stream"
    return FileResponse(path, media_type=media_type, filename=path.name)


@app.get("/api/macros/{macro_id}/export.json")
async def export_macro_json(macro_id: str) -> Response:
    macro = storage.get_macro(macro_id)
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    return Response(json_export(macro), media_type="application/json", headers={"Content-Disposition": f'attachment; filename="{macro.name}.json"'})


@app.get("/api/macros/{macro_id}/export.py")
async def export_macro_python(macro_id: str) -> Response:
    macro = storage.get_macro(macro_id)
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    return Response(python_export(macro), media_type="text/x-python", headers={"Content-Disposition": f'attachment; filename="{macro.name}.py"'})


@app.get("/api/sessions")
async def list_sessions() -> list[dict[str, Any]]:
    return browser_service.list_sessions()


@app.post("/api/sessions/{session_name}/open")
async def open_session(session_name: str, url: str | None = None) -> dict[str, Any]:
    try:
        return await browser_service.open_manual_session(session_name, url)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/sessions/{session_name}/save")
async def save_session(session_name: str) -> dict[str, Any]:
    try:
        path = await browser_service.save_manual_session(session_name)
        return {"saved": True, "name": session_name, "path": path.name}
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.delete("/api/sessions/{session_name}")
async def delete_session(session_name: str) -> dict[str, Any]:
    await browser_service.close_manual_session(session_name)
    path = sessions_dir() / f"{re.sub(r'[^a-zA-Z0-9_-]', '_', session_name)}.json"
    if path.exists():
        path.unlink()
    return {"deleted": True}


@app.get("/")
async def root() -> JSONResponse:
    return JSONResponse({"service": "Automata", "frontend": "Run npm run dev in frontend/ or use the built app."})

