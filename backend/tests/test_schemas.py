from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.planner import fallback_macro
from backend.schemas import Macro, PlanRequest, Step


def test_catalog_plan_is_schema_valid_and_keeps_variable_references_structural() -> None:
    macro = fallback_macro(
        PlanRequest(
            starting_url="http://127.0.0.1:8000/demo/catalog",
            instruction="Search for {{search_term}} across up to {{max_pages}} pages and export results.",
            variables={"search_term": "desk", "max_pages": 2},
            use_model=False,
        )
    )
    assert isinstance(macro, Macro)
    fill_step = next(step for step in macro.steps if step.action == "fill")
    assert fill_step.value_ref == "search_term"
    assert fill_step.value is None
    assert macro.steps[-1].action == "export"


def test_macro_rejects_unknown_parameter_references() -> None:
    with pytest.raises(ValidationError, match="unknown parameter"):
        Macro(
            name="Invalid",
            starting_url="https://example.com",
            parameters=[],
            steps=[
                Step(
                    id="fill",
                    action="fill",
                    description="Fill an input",
                    locator={"strategy": "label", "value": "Name"},
                    value_ref="missing",
                )
            ],
        )


def test_step_limits_are_bounded() -> None:
    with pytest.raises(ValidationError):
        Step(id="wait", action="screenshot", description="Too long", timeout_ms=121_000)

