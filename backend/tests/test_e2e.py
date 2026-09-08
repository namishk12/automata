from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest


ROOT = Path(__file__).resolve().parents[2]


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def live_server(tmp_path_factory: pytest.TempPathFactory):
    port = free_port()
    data_path = tmp_path_factory.mktemp("e2e-data")
    environment = os.environ.copy()
    environment.update({"AUTOMATA_DATA_DIR": str(data_path), "AUTOMATA_BROWSER_HEADLESS": "true"})
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"{base_url}/api/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(.25)
        else:
            output = process.stdout.read() if process.stdout else ""
            raise RuntimeError(f"Server did not start: {output}")
        yield base_url
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


@pytest.mark.e2e
def test_local_demo_plan_execute_and_export(live_server: str) -> None:
    with httpx.Client(base_url=live_server, timeout=10) as client:
        plan_response = client.post(
            "/api/plans/generate",
            json={
                "starting_url": f"{live_server}/demo/catalog",
                "instruction": "Search for {{search_term}} across up to {{max_pages}} pages and export the results to CSV.",
                "variables": {"search_term": "desk", "max_pages": 2},
                "use_model": False,
            },
        )
        assert plan_response.status_code == 200
        macro = plan_response.json()["macro"]
        assert macro["schema_version"] == "1.0"
        assert any(step["action"] == "extract_records" for step in macro["steps"])

        saved = client.post("/api/macros", json=macro)
        assert saved.status_code == 200
        saved_macro = saved.json()
        started = client.post("/api/runs", json={"macro_id": saved_macro["id"], "variables": {"search_term": "desk", "max_pages": 2}})
        assert started.status_code == 200, started.text
        run_id = started.json()["id"]

        for _ in range(120):
            run = client.get(f"/api/runs/{run_id}").json()
            if run["status"] in {"Completed", "Failed", "Cancelled"}:
                break
            time.sleep(.25)
        assert run["status"] == "Completed", run
        assert len(run["outputs"]["records"]) >= 3
        assert any(artifact["name"].endswith(".csv") for artifact in run["artifacts"])
        assert client.get(f"/api/runs/{run_id}/screenshot").status_code == 200
        events = client.get(f"/api/runs/{run_id}/events").text
        assert "step_completed" in events

