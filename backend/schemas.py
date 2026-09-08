"""Versioned, validated data contracts for plans, macros, and runs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


SCHEMA_VERSION = "1.0"
ActionType = Literal[
    "navigate",
    "click",
    "fill",
    "clear",
    "select",
    "check",
    "uncheck",
    "press",
    "wait_for",
    "read",
    "extract_records",
    "paginate",
    "new_tab",
    "screenshot",
    "download",
    "export",
    "assert",
]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LocatorSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["role", "label", "test_id", "text", "css", "placeholder"]
    value: str = Field(min_length=1)
    name: str | None = None
    exact: bool = False


class ConditionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["visible", "hidden", "text", "url_contains", "attribute"]
    locator: LocatorSpec | None = None
    expected: str | None = None
    attribute: str | None = None


class RecordField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    locator: LocatorSpec
    attribute: str | None = None


class PaginationSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    next_locator: LocatorSpec
    max_pages: int | str = 1

    @model_validator(mode="after")
    def validate_limit(self) -> "PaginationSpec":
        if isinstance(self.max_pages, int) and not 1 <= self.max_pages <= 100:
            raise ValueError("max_pages must be between 1 and 100")
        if isinstance(self.max_pages, str) and not self.max_pages:
            raise ValueError("max_pages parameter reference cannot be empty")
        return self


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-zA-Z0-9_-]{2,80}$")
    action: ActionType
    description: str = Field(min_length=1, max_length=240)
    page: str | None = None
    locator: LocatorSpec | None = None
    url: str | None = None
    value: str | int | float | bool | None = None
    value_ref: str | None = Field(default=None, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    key: str | None = None
    condition: ConditionSpec | None = None
    output_key: str | None = Field(default=None, pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    record_locator: LocatorSpec | None = None
    fields: list[RecordField] = Field(default_factory=list)
    pagination: PaginationSpec | None = None
    filename: str | None = None
    export_format: Literal["csv", "json"] = "csv"
    timeout_ms: int = Field(default=15_000, ge=250, le=120_000)
    retry_attempts: int = Field(default=1, ge=0, le=3)
    success_condition: ConditionSpec | None = None

    @model_validator(mode="after")
    def validate_action_fields(self) -> "Step":
        needs_locator = {
            "click",
            "fill",
            "clear",
            "select",
            "check",
            "uncheck",
            "press",
            "read",
            "download",
            "assert",
        }
        if self.action in needs_locator and self.locator is None:
            raise ValueError(f"{self.action} steps require a locator")
        if self.action == "navigate" and not self.url:
            raise ValueError("navigate steps require a url")
        if self.action == "fill" and self.value is None and self.value_ref is None:
            raise ValueError("fill steps require value or value_ref")
        if self.action == "select" and self.value is None and self.value_ref is None:
            raise ValueError("select steps require value or value_ref")
        if self.action == "press" and not self.key:
            raise ValueError("press steps require key")
        if self.action == "wait_for" and self.condition is None:
            raise ValueError("wait_for steps require condition")
        if self.action == "extract_records":
            if self.record_locator is None:
                raise ValueError("extract_records steps require record_locator")
            if not self.fields:
                raise ValueError("extract_records steps require fields")
        if self.action == "paginate" and self.pagination is None:
            raise ValueError("paginate steps require pagination")
        if self.action == "export" and not self.output_key:
            raise ValueError("export steps require output_key")
        if self.action == "assert" and self.condition is None:
            raise ValueError("assert steps require condition")
        return self


class ParameterDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$")
    label: str
    type: Literal["text", "number", "date", "boolean", "secret"] = "text"
    required: bool = True
    default: str | int | float | bool | None = None


class Macro(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal[SCHEMA_VERSION] = SCHEMA_VERSION
    id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=500)
    starting_url: str = Field(min_length=1)
    parameters: list[ParameterDefinition] = Field(default_factory=list)
    steps: list[Step] = Field(min_length=1, max_length=100)
    expected_outputs: list[str] = Field(default_factory=list)
    created_at: str | None = None
    modified_at: str | None = None

    @model_validator(mode="after")
    def validate_macro(self) -> "Macro":
        names = [parameter.name for parameter in self.parameters]
        if len(names) != len(set(names)):
            raise ValueError("parameter names must be unique")
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step ids must be unique")
        known = set(names)
        for step in self.steps:
            for ref in [step.value_ref, step.pagination and step.pagination.max_pages]:
                if isinstance(ref, str) and ref not in known:
                    raise ValueError(f"step {step.id} references unknown parameter {ref}")
        return self


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starting_url: str = Field(min_length=1)
    instruction: str = Field(min_length=5, max_length=8_000)
    variables: dict[str, Any] = Field(default_factory=dict)
    use_model: bool = True


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    macro: Macro | None = None
    macro_id: str | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    session_name: str = "default"
    ai_repair: bool = False
    repair_attempts: int = Field(default=2, ge=0, le=2)
    pause_between_steps: bool = False

    @model_validator(mode="after")
    def one_macro_source(self) -> "RunRequest":
        if bool(self.macro) == bool(self.macro_id):
            raise ValueError("provide exactly one of macro or macro_id")
        return self


class ModelSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    timeout_seconds: int = Field(default=45, ge=5, le=180)
    supports_images: bool = False
    supports_structured_output: bool = True
    api_key_configured: bool = False
    source: Literal["environment", "database", "default"] = "default"


class ModelSettingsUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=1)
    model: str = Field(min_length=1)
    timeout_seconds: int = Field(default=45, ge=5, le=180)
    supports_images: bool = False
    supports_structured_output: bool = True
    api_key: str | None = None


class RepairRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    apply: bool = False
