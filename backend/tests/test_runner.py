from __future__ import annotations

import asyncio
from pathlib import Path

from backend.browser import BrowserService, ExecutionManager
from backend.db import Database
from backend.schemas import Macro, Step
from backend.storage import Storage


class FakePage:
    url = "http://fake.local/"

    async def goto(self, url: str, **_: object) -> None:
        self.url = url

    async def screenshot(self, path: str, **_: object) -> None:
        Path(path).write_bytes(b"fake-png")


class FakeContext:
    def __init__(self) -> None:
        self.pages = []

    async def new_page(self) -> FakePage:
        page = FakePage()
        self.pages.append(page)
        return page

    async def close(self) -> None:
        return None


class FakeBrowser(BrowserService):
    async def new_context(self, session_name: str = "default") -> FakeContext:
        return FakeContext()


def make_storage(tmp_path: Path) -> Storage:
    database = Database(tmp_path / "test.sqlite3")
    database.initialize()
    return Storage(database)


def test_variable_resolution_and_required_validation(tmp_path: Path) -> None:
    storage = make_storage(tmp_path)
    manager = ExecutionManager(storage, FakeBrowser())
    macro = Macro(
        name="Variable test",
        starting_url="https://example.com/{{id}}",
        parameters=[{"name": "id", "label": "ID", "required": True}],
        steps=[Step(id="nav", action="navigate", description="Open", url="https://example.com")],
    )
    assert manager._resolve("{{id}}", {"id": "42"}, {}) == "42"
    assert manager._validate_variables(macro, {"id": "42"})["id"] == "42"


def test_cancellation_is_recorded_between_steps(tmp_path: Path) -> None:
    async def scenario() -> None:
        storage = make_storage(tmp_path)
        manager = ExecutionManager(storage, FakeBrowser())
        macro = Macro(name="Cancel test", starting_url="https://example.com", steps=[Step(id="nav", action="navigate", description="Open", url="https://example.com")])
        run_id = "cancel-run"
        storage.create_run(run_id, None, {"macro": macro.model_dump(mode="json")}, status="Planning")
        await manager.start_run(run_id, macro, {}, {})
        await manager.stop(run_id)
        await manager.controls[run_id].task
        assert storage.get_run(run_id)["status"] == "Cancelled"

    asyncio.run(scenario())


def test_browser_failure_is_actionable(tmp_path: Path) -> None:
    class FailingBrowser(FakeBrowser):
        async def new_context(self, session_name: str = "default") -> FakeContext:
            class FailingContext(FakeContext):
                async def new_page(self) -> FakePage:
                    page = FakePage()

                    async def fail(*_: object, **__: object) -> None:
                        raise RuntimeError("navigation failed")

                    page.goto = fail  # type: ignore[method-assign]
                    return page

            return FailingContext()

    async def scenario() -> None:
        storage = make_storage(tmp_path)
        manager = ExecutionManager(storage, FailingBrowser())
        macro = Macro(name="Failure test", starting_url="https://example.com", steps=[Step(id="nav", action="navigate", description="Open", url="https://example.com")])
        run_id = "failure-run"
        storage.create_run(run_id, None, {"macro": macro.model_dump(mode="json")}, status="Planning")
        await manager.start_run(run_id, macro, {}, {})
        await manager.controls[run_id].task
        record = storage.get_run(run_id)
        assert record["status"] == "Failed"
        assert "navigation failed" in record["error"]["message"]

    asyncio.run(scenario())
