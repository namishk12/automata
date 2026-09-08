"""Deterministic Playwright execution with bounded lifecycle and repair hooks."""

from __future__ import annotations

import asyncio
import csv
import json
import re
import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from .config import CONFIG
from .db import data_dir
from .model_adapter import ModelAdapter, ModelError
from .schemas import ConditionSpec, LocatorSpec, Macro, Step, utc_now
from .storage import Storage

try:  # Keep schema-only tests usable before Playwright is installed.
    from playwright.async_api import Browser, BrowserContext, Locator, Page, TimeoutError as PlaywrightTimeoutError, async_playwright
except ImportError:  # pragma: no cover - exercised only in an uninstalled environment
    Browser = BrowserContext = Locator = Page = Any  # type: ignore[misc,assignment]
    PlaywrightTimeoutError = TimeoutError  # type: ignore[assignment]
    async_playwright = None  # type: ignore[assignment]


class BrowserUnavailable(RuntimeError):
    pass


class RunCancelled(RuntimeError):
    pass


class AmbiguousLocator(RuntimeError):
    pass


def artifacts_dir(run_id: str) -> Path:
    path = data_dir() / "runs" / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def sessions_dir() -> Path:
    path = data_dir() / "sessions"
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass
class RunControl:
    run_id: str
    paused: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)
    subscribers: set[asyncio.Queue[dict[str, Any]]] = field(default_factory=set)
    task: asyncio.Task[None] | None = None
    page: Any = None
    context: Any = None
    repairs: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.paused.set()


class BrowserService:
    """Owns the visible Chromium process and explicitly saved login contexts."""

    def __init__(self) -> None:
        self.playwright: Any = None
        self.browser: Any = None
        self.manual_contexts: dict[str, Any] = {}

    async def ensure_browser(self) -> Any:
        if async_playwright is None:
            raise BrowserUnavailable("Playwright is not installed. Run .\\scripts\\start.ps1 after installing requirements.")
        if self.browser is None or not self.browser.is_connected():
            self.playwright = await async_playwright().start()
            self.browser = await self.playwright.chromium.launch(headless=CONFIG.browser_headless)
        return self.browser

    async def new_context(self, session_name: str = "default") -> Any:
        browser = await self.ensure_browser()
        state_path = sessions_dir() / f"{re.sub(r'[^a-zA-Z0-9_-]', '_', session_name)}.json"
        options: dict[str, Any] = {"accept_downloads": True, "viewport": {"width": 1440, "height": 900}}
        if state_path.exists():
            options["storage_state"] = str(state_path)
        return await browser.new_context(**options)

    async def open_manual_session(self, session_name: str, url: str | None = None) -> dict[str, Any]:
        context = self.manual_contexts.get(session_name)
        if context is None:
            context = await self.new_context(session_name)
            self.manual_contexts[session_name] = context
        page = context.pages[0] if context.pages else await context.new_page()
        if url:
            await page.goto(url, wait_until="domcontentloaded", timeout=CONFIG.browser_timeout_ms)
        return {"session_name": session_name, "url": page.url, "visible": not CONFIG.browser_headless}

    async def save_manual_session(self, session_name: str) -> Path:
        context = self.manual_contexts.get(session_name)
        if context is None:
            raise ValueError("Open the browser session before saving it.")
        path = sessions_dir() / f"{re.sub(r'[^a-zA-Z0-9_-]', '_', session_name)}.json"
        await context.storage_state(path=str(path))
        return path

    async def close_manual_session(self, session_name: str) -> None:
        context = self.manual_contexts.pop(session_name, None)
        if context:
            await context.close()

    def list_sessions(self) -> list[dict[str, Any]]:
        result = []
        for path in sorted(sessions_dir().glob("*.json")):
            result.append({"name": path.stem, "saved": True, "path": path.name})
        for name in self.manual_contexts:
            if not any(item["name"] == name for item in result):
                result.append({"name": name, "saved": False, "path": None})
        return result

    async def close(self) -> None:
        for context in list(self.manual_contexts.values()):
            await context.close()
        self.manual_contexts.clear()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        self.browser = None
        self.playwright = None


class ExecutionManager:
    def __init__(self, storage: Storage, browser: BrowserService | None = None) -> None:
        self.storage = storage
        self.browser_service = browser or BrowserService()
        self.controls: dict[str, RunControl] = {}
        self.active_run_id: str | None = None
        self._lock = asyncio.Lock()

    async def start_run(self, run_id: str, macro: Macro, variables: dict[str, Any], options: dict[str, Any]) -> None:
        async with self._lock:
            if self.active_run_id and self._is_active(self.active_run_id):
                raise RuntimeError("Only one browser run can be active at a time.")
            control = RunControl(run_id)
            self.controls[run_id] = control
            self.active_run_id = run_id
            control.task = asyncio.create_task(self._run(control, macro, variables, options))

    def _is_active(self, run_id: str) -> bool:
        record = self.storage.get_run(run_id)
        return bool(record and record.get("status") in {"Planning", "Running", "Paused"})

    async def pause(self, run_id: str) -> dict[str, Any]:
        control = self._control(run_id)
        control.paused.clear()
        record = self.storage.update_run(run_id, status="Paused")
        await self.emit(run_id, "status", {"status": "Paused", "message": "Execution paused between actions."})
        return record or {}

    async def resume(self, run_id: str) -> dict[str, Any]:
        control = self._control(run_id)
        control.paused.set()
        record = self.storage.update_run(run_id, status="Running")
        await self.emit(run_id, "status", {"status": "Running", "message": "Execution resumed."})
        return record or {}

    async def stop(self, run_id: str) -> dict[str, Any]:
        control = self._control(run_id)
        control.cancelled.set()
        control.paused.set()
        await self.emit(run_id, "status", {"status": "Stopping", "message": "Stop requested; finishing the current browser call."})
        return self.storage.get_run(run_id) or {}

    def _control(self, run_id: str) -> RunControl:
        control = self.controls.get(run_id)
        if control is None:
            raise KeyError(f"Run {run_id} is not active.")
        return control

    async def subscribe(self, run_id: str) -> asyncio.Queue[dict[str, Any]]:
        control = self.controls.setdefault(run_id, RunControl(run_id))
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        control.subscribers.add(queue)
        return queue

    def unsubscribe(self, run_id: str, queue: asyncio.Queue[dict[str, Any]]) -> None:
        control = self.controls.get(run_id)
        if control:
            control.subscribers.discard(queue)

    async def emit(self, run_id: str, event_type: str, data: dict[str, Any]) -> None:
        event_id = self.storage.append_event(run_id, event_type, data)
        payload = {"id": event_id, "type": event_type, "created_at": utc_now(), **data}
        control = self.controls.get(run_id)
        if control:
            for queue in list(control.subscribers):
                await queue.put(payload)

    async def _wait_control(self, control: RunControl) -> None:
        if control.cancelled.is_set():
            raise RunCancelled("The user stopped this run.")
        await control.paused.wait()
        if control.cancelled.is_set():
            raise RunCancelled("The user stopped this run.")

    @staticmethod
    def _resolve(value: Any, variables: dict[str, Any], defaults: dict[str, Any]) -> Any:
        if isinstance(value, str) and value in variables:
            return variables[value]
        if isinstance(value, str) and value in defaults:
            return defaults[value]
        if isinstance(value, str) and value.startswith("{{") and value.endswith("}}"):
            key = value[2:-2].strip()
            return variables.get(key, defaults.get(key))
        return value

    def _validate_variables(self, macro: Macro, variables: dict[str, Any]) -> dict[str, Any]:
        defaults = {parameter.name: parameter.default for parameter in macro.parameters if parameter.default is not None}
        values = {**defaults, **variables}
        missing = [parameter.name for parameter in macro.parameters if parameter.required and values.get(parameter.name) in (None, "")]
        if missing:
            raise ValueError(f"Missing required parameters: {', '.join(missing)}")
        return values

    async def _run(self, control: RunControl, macro: Macro, supplied_variables: dict[str, Any], options: dict[str, Any]) -> None:
        run_id = control.run_id
        context: Any = None
        try:
            variables = self._validate_variables(macro, supplied_variables)
            self.storage.update_run(run_id, status="Running", started_at=utc_now(), variables=variables)
            await self.emit(run_id, "status", {"status": "Running", "message": "Browser run started."})
            context = await self.browser_service.new_context(options.get("session_name", "default"))
            control.context = context
            page = await context.new_page()
            control.page = page
            outputs: dict[str, Any] = {}
            artifacts: list[dict[str, Any]] = []
            max_seconds = CONFIG.max_run_minutes * 60
            async with asyncio.timeout(max_seconds):
                for index, step in enumerate(macro.steps):
                    await self._wait_control(control)
                    await self.emit(
                        run_id,
                        "step_started",
                        {"step_id": step.id, "index": index, "description": step.description, "action": step.action},
                    )
                    started = asyncio.get_running_loop().time()
                    try:
                        result = await self._execute_with_retries(control, step, variables, outputs, artifacts)
                    except RunCancelled:
                        raise
                    except Exception as exc:
                        failure = await self._handle_failure(control, macro, step, variables, outputs, artifacts, exc, options)
                        if failure is not None:
                            result = failure
                        else:
                            raise
                    if result is not None:
                        if isinstance(result, dict):
                            outputs.update(result)
                    elapsed_ms = round((asyncio.get_running_loop().time() - started) * 1000)
                    await self.emit(
                        run_id,
                        "step_completed",
                        {"step_id": step.id, "index": index, "elapsed_ms": elapsed_ms, "outputs": _preview(result)},
                    )
                    if options.get("pause_between_steps") and index < len(macro.steps) - 1:
                        control.paused.clear()
                        self.storage.update_run(run_id, status="Paused")
                        await self.emit(run_id, "status", {"status": "Paused", "message": "Paused between steps by run option."})
                    if control.cancelled.is_set():
                        raise RunCancelled("The user stopped this run.")
            self.storage.update_run(
                run_id,
                status="Completed",
                finished_at=utc_now(),
                outputs=outputs,
                artifacts=artifacts,
                current_url=getattr(control.page, "url", None),
                repairs=control.repairs,
            )
            await self.emit(run_id, "status", {"status": "Completed", "message": "Run completed successfully.", "outputs": _preview(outputs)})
        except RunCancelled as exc:
            self.storage.update_run(run_id, status="Cancelled", finished_at=utc_now(), error={"kind": "cancelled", "message": str(exc)}, repairs=control.repairs)
            await self.emit(run_id, "status", {"status": "Cancelled", "message": str(exc)})
        except asyncio.TimeoutError:
            error = {"kind": "run_timeout", "message": f"Run exceeded the {CONFIG.max_run_minutes}-minute limit."}
            self.storage.update_run(run_id, status="Failed", finished_at=utc_now(), error=error, repairs=control.repairs)
            await self.emit(run_id, "failed", error)
        except Exception as exc:
            error = {"kind": type(exc).__name__, "message": str(exc), "url": getattr(control.page, "url", None)}
            self.storage.update_run(run_id, status="Failed", finished_at=utc_now(), error=error, repairs=control.repairs)
            await self.emit(run_id, "failed", error)
        finally:
            if context is not None:
                await context.close()
            if self.active_run_id == run_id:
                self.active_run_id = None
            await self.emit(run_id, "done", {"status": (self.storage.get_run(run_id) or {}).get("status", "Failed")})

    async def _execute_with_retries(
        self, control: RunControl, step: Step, variables: dict[str, Any], outputs: dict[str, Any], artifacts: list[dict[str, Any]]
    ) -> Any:
        attempts = step.retry_attempts
        # Repeating a submit or download after an uncertain timeout can duplicate a side effect.
        if step.action in {"click", "download", "new_tab"}:
            attempts = 0
        last_error: Exception | None = None
        for attempt in range(attempts + 1):
            await self._wait_control(control)
            try:
                return await self._execute_step(control, step, variables, outputs, artifacts)
            except Exception as exc:
                last_error = exc
                if attempt < attempts:
                    await self.emit(control.run_id, "log", {"message": f"Retrying {step.id} ({attempt + 1}/{attempts})."})
        assert last_error is not None
        raise last_error

    async def _execute_step(
        self, control: RunControl, step: Step, variables: dict[str, Any], outputs: dict[str, Any], artifacts: list[dict[str, Any]]
    ) -> Any:
        page = control.page
        if page is None:
            raise RuntimeError("No active browser page.")
        timeout = step.timeout_ms
        if step.action == "navigate":
            await page.goto(str(self._resolve(step.url, variables, {})), wait_until="domcontentloaded", timeout=timeout)
            return {"current_url": page.url}
        if step.action == "screenshot":
            path = artifacts_dir(control.run_id) / f"{step.id}.png"
            await page.screenshot(path=str(path), full_page=False)
            artifact = {"kind": "screenshot", "name": path.name, "url": f"/api/runs/{control.run_id}/screenshot"}
            artifacts.append(artifact)
            await self.emit(control.run_id, "screenshot", artifact)
            return {"screenshot": str(path)}
        if step.action == "extract_records":
            records = await self._extract_records(control, step, variables)
            return {step.output_key or "records": records}
        if step.action == "export":
            values = outputs.get(step.output_key or "records", [])
            suffix = "json" if step.export_format == "json" else "csv"
            filename = step.filename or f"{step.output_key or 'results'}.{suffix}"
            filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", filename)
            path = artifacts_dir(control.run_id) / filename
            if step.export_format == "json":
                path.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            else:
                rows = values if isinstance(values, list) else []
                keys = sorted({key for row in rows if isinstance(row, dict) for key in row})
                with path.open("w", newline="", encoding="utf-8") as handle:
                    writer = csv.DictWriter(handle, fieldnames=keys or ["value"])
                    writer.writeheader()
                    for row in rows:
                        writer.writerow(row if isinstance(row, dict) else {"value": row})
            artifact = {"kind": "file", "name": filename, "url": f"/api/runs/{control.run_id}/artifacts/{filename}"}
            artifacts.append(artifact)
            await self.emit(control.run_id, "artifact", artifact)
            return {"export": artifact}
        if step.action in {"click", "fill", "clear", "select", "check", "uncheck", "press", "read", "download", "assert"}:
            locator = await self._strict_locator(page, step.locator)
            value = variables.get(step.value_ref) if step.value_ref else self._resolve(step.value, variables, {})
            if step.action == "click":
                await locator.click(timeout=timeout)
                return None
            if step.action == "fill":
                await locator.fill(str(self._resolve(value, variables, {})), timeout=timeout)
                return None
            if step.action == "clear":
                await locator.fill("", timeout=timeout)
                return None
            if step.action == "select":
                await locator.select_option(str(value), timeout=timeout)
                return None
            if step.action == "check":
                await locator.check(timeout=timeout)
                return None
            if step.action == "uncheck":
                await locator.uncheck(timeout=timeout)
                return None
            if step.action == "press":
                await locator.press(step.key or "Enter", timeout=timeout)
                return None
            if step.action == "read":
                content = await self._read_locator(locator, step.locator)
                return {step.output_key or "value": content}
            if step.action == "download":
                path = artifacts_dir(control.run_id) / (step.filename or "download.bin")
                async with page.expect_download(timeout=timeout) as download_info:
                    await locator.click(timeout=timeout)
                download = await download_info.value
                await download.save_as(str(path))
                artifact = {"kind": "file", "name": path.name, "url": f"/api/runs/{control.run_id}/artifacts/{path.name}"}
                artifacts.append(artifact)
                await self.emit(control.run_id, "artifact", artifact)
                return {"download": artifact}
            if step.action == "assert":
                await self._check_condition(page, step.condition, timeout)
                return None
        if step.action == "wait_for":
            await self._check_condition(page, step.condition, timeout)
            return None
        if step.action == "new_tab":
            async with control.context.expect_page(timeout=timeout) as page_info:
                locator = await self._strict_locator(page, step.locator)
                await locator.click(timeout=timeout)
            control.page = await page_info.value
            await control.page.wait_for_load_state("domcontentloaded", timeout=timeout)
            return {"current_url": control.page.url}
        if step.action == "paginate":
            await self._paginate(control, step, variables, outputs)
            return None
        raise ValueError(f"Unsupported action {step.action}")

    async def _strict_locator(self, page: Any, spec: LocatorSpec | None, allow_many: bool = False) -> Any:
        if spec is None:
            raise ValueError("This action requires a locator.")
        if spec.strategy == "role":
            locator = page.get_by_role(spec.value, name=spec.name, exact=spec.exact)
        elif spec.strategy == "label":
            locator = page.get_by_label(spec.value, exact=spec.exact)
        elif spec.strategy == "test_id":
            locator = page.get_by_test_id(spec.value)
        elif spec.strategy == "text":
            locator = page.get_by_text(spec.value, exact=spec.exact)
        elif spec.strategy == "placeholder":
            locator = page.get_by_placeholder(spec.value, exact=spec.exact)
        else:
            locator = page.locator(spec.value)
        count = await locator.count()
        if count > 1 and not allow_many:
            raise AmbiguousLocator(f"Locator {spec.strategy}={spec.value!r} matched {count} elements; use a more specific locator.")
        return locator

    async def _read_locator(self, locator: Any, spec: LocatorSpec | None, attribute: str | None = None) -> str:
        count = await locator.count()
        if count == 0:
            raise ValueError(f"Locator did not match: {spec}")
        if attribute:
            value = await locator.get_attribute(attribute)
            return value or ""
        return (await locator.inner_text()).strip()

    async def _check_condition(self, page: Any, condition: ConditionSpec | None, timeout: int) -> None:
        if condition is None:
            raise ValueError("Missing condition.")
        if condition.kind == "url_contains":
            await page.wait_for_url(f"**{condition.expected or ''}**", timeout=timeout)
            return
        locator = await self._strict_locator(page, condition.locator, allow_many=condition.kind in {"visible", "hidden"})
        if condition.kind == "visible":
            await locator.first.wait_for(state="visible", timeout=timeout)
        elif condition.kind == "hidden":
            await locator.first.wait_for(state="hidden", timeout=timeout)
        elif condition.kind == "text":
            actual = await locator.inner_text(timeout=timeout)
            if (condition.expected or "") not in actual:
                raise AssertionError(f"Expected text {condition.expected!r} was not present.")
        elif condition.kind == "attribute":
            actual = await locator.get_attribute(condition.attribute or "")
            if actual != condition.expected:
                raise AssertionError(f"Expected attribute {condition.attribute}={condition.expected!r}, got {actual!r}.")

    async def _extract_records(self, control: RunControl, step: Step, variables: dict[str, Any]) -> list[dict[str, Any]]:
        page = control.page
        if page is None or step.record_locator is None:
            raise ValueError("Record extraction needs a page and record locator.")
        max_pages = int(self._resolve(step.pagination.max_pages if step.pagination else 1, variables, {}))
        max_pages = max(1, min(max_pages, 100))
        all_records: list[dict[str, Any]] = []
        for page_index in range(max_pages):
            rows_locator = await self._strict_locator(page, step.record_locator, allow_many=True)
            await rows_locator.first.wait_for(state="visible", timeout=step.timeout_ms)
            row_count = await rows_locator.count()
            for row_index in range(row_count):
                row = rows_locator.nth(row_index)
                record: dict[str, Any] = {}
                for field in step.fields:
                    field_locator = self._nested_locator(row, field.locator)
                    record[field.name] = await self._read_locator(field_locator, field.locator, field.attribute)
                all_records.append(record)
            await self.emit(control.run_id, "log", {"message": f"Extracted {row_count} records from page {page_index + 1}."})
            if not step.pagination or page_index >= max_pages - 1:
                break
            next_locator = await self._strict_locator(page, step.pagination.next_locator)
            if await next_locator.count() == 0 or not await next_locator.is_visible() or not await next_locator.is_enabled():
                break
            await next_locator.click(timeout=step.timeout_ms)
            await page.wait_for_load_state("domcontentloaded", timeout=step.timeout_ms)
        return all_records

    @staticmethod
    def _nested_locator(root: Any, spec: LocatorSpec) -> Any:
        if spec.strategy == "role":
            return root.get_by_role(spec.value, name=spec.name, exact=spec.exact)
        if spec.strategy == "label":
            return root.get_by_label(spec.value, exact=spec.exact)
        if spec.strategy == "test_id":
            return root.get_by_test_id(spec.value)
        if spec.strategy == "text":
            return root.get_by_text(spec.value, exact=spec.exact)
        if spec.strategy == "placeholder":
            return root.get_by_placeholder(spec.value, exact=spec.exact)
        return root.locator(spec.value)

    async def _paginate(self, control: RunControl, step: Step, variables: dict[str, Any], outputs: dict[str, Any]) -> None:
        if step.pagination is None:
            raise ValueError("Pagination config is required.")
        max_pages = int(self._resolve(step.pagination.max_pages, variables, {}))
        for _ in range(max(0, min(max_pages - 1, 100))):
            page = control.page
            locator = await self._strict_locator(page, step.pagination.next_locator)
            if await locator.count() == 0 or not await locator.is_visible() or not await locator.is_enabled():
                return
            await locator.click(timeout=step.timeout_ms)
            await page.wait_for_load_state("domcontentloaded", timeout=step.timeout_ms)

    async def _handle_failure(
        self,
        control: RunControl,
        macro: Macro,
        step: Step,
        variables: dict[str, Any],
        outputs: dict[str, Any],
        artifacts: list[dict[str, Any]],
        exc: Exception,
        options: dict[str, Any],
    ) -> dict[str, Any] | None:
        screenshot = None
        if control.page is not None:
            path = artifacts_dir(control.run_id) / f"failure-{step.id}.png"
            try:
                await control.page.screenshot(path=str(path))
                screenshot = path.name
                artifacts.append({"kind": "screenshot", "name": path.name, "url": f"/api/runs/{control.run_id}/screenshot?name={path.name}"})
            except Exception:
                pass
        details = {
            "step_id": step.id,
            "message": str(exc),
            "url": getattr(control.page, "url", None),
            "screenshot": screenshot,
            "page_excerpt": await self._page_excerpt(control.page),
        }
        await self.emit(control.run_id, "step_failed", details)
        if not options.get("ai_repair"):
            return None
        max_attempts = int(options.get("repair_attempts", 2))
        if len([entry for entry in control.repairs if entry.get("step_id") == step.id]) >= max_attempts:
            return None
        for attempt in range(max_attempts):
            if len([entry for entry in control.repairs if entry.get("step_id") == step.id]) >= max_attempts:
                break
            repair_entry: dict[str, Any] = {"step_id": step.id, "attempt": attempt + 1, "original": step.model_dump(mode="json")}
            try:
                adapter = ModelAdapter.from_storage(self.storage)
                if not adapter.settings.api_key_configured:
                    raise ModelError("AI-assisted repair is enabled, but no model API key is configured.")
                response = await adapter.complete_json(
                    "Return JSON with one key named step containing a repaired Macro step. Change only locator, timeout_ms, retry_attempts, success_condition, or description. Preserve action, URL, and submitted values.",
                    json.dumps({"step": step.model_dump(mode="json"), "error": details, "parameters": list(variables)}, ensure_ascii=False),
                )
                candidate = Step.model_validate(response.get("step", response))
                if not self._safe_repair(step, candidate):
                    raise ValueError("The proposed repair changed the action or submitted value and was rejected.")
                repair_entry["proposal"] = candidate.model_dump(mode="json")
                repaired_result = await self._execute_with_retries(control, candidate, variables, outputs, artifacts)
                repair_entry["outcome"] = "succeeded"
                control.repairs.append(repair_entry)
                await self.emit(control.run_id, "repair", repair_entry)
                return repaired_result
            except Exception as repair_exc:
                repair_entry["outcome"] = "failed"
                repair_entry["error"] = str(repair_exc)
                control.repairs.append(repair_entry)
                await self.emit(control.run_id, "repair", repair_entry)
        return None

    @staticmethod
    def _safe_repair(original: Step, candidate: Step) -> bool:
        return (
            original.action == candidate.action
            and original.url == candidate.url
            and original.value == candidate.value
            and original.value_ref == candidate.value_ref
            and original.key == candidate.key
            and original.filename == candidate.filename
        )

    @staticmethod
    async def _page_excerpt(page: Any) -> str:
        if page is None:
            return ""
        try:
            text = await page.locator("body").inner_text(timeout=1500)
            return re.sub(r"\s+", " ", text)[:1200]
        except Exception:
            return ""


def _preview(value: Any) -> Any:
    if isinstance(value, list):
        return {"count": len(value), "sample": value[:3]}
    if isinstance(value, dict):
        return {key: _preview(item) for key, item in list(value.items())[:10]}
    if isinstance(value, str) and len(value) > 160:
        return value[:160] + "…"
    return value
