"""Environment-backed configuration with safe defaults for local development."""

from __future__ import annotations

import os
from dataclasses import dataclass


def env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class AppConfig:
    host: str = os.getenv("AUTOMATA_HOST", "127.0.0.1")
    port: int = int(os.getenv("AUTOMATA_PORT", "8000"))
    browser_headless: bool = env_bool("AUTOMATA_BROWSER_HEADLESS", False)
    browser_timeout_ms: int = int(os.getenv("AUTOMATA_BROWSER_TIMEOUT_MS", "15000"))
    max_run_minutes: int = int(os.getenv("AUTOMATA_MAX_RUN_MINUTES", "15"))
    planner_inspect_page: bool = env_bool("AUTOMATA_PLANNER_INSPECT_PAGE", False)


CONFIG = AppConfig()

