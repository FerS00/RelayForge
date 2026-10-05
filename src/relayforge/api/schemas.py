from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


class ConversationCreate(BaseModel):
    pass


class MessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("content")
    @classmethod
    def content_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("El mensaje no puede estar vacío.")
        return value


class JobCreate(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    request_text: str = Field(min_length=1, max_length=100_000)
    workflow: Literal["auto", "trivial", "feature", "security"] = "auto"
    repository_id: str | None = None
    agent: Literal["claude", "codex"] = "claude"
    require_plan_approval: bool = False
    model: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    implementation_model: str | None = Field(
        default=None, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"
    )
    audit_model: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("El título no puede estar vacío.")
        return value.strip() if value else value

    @field_validator("request_text")
    @classmethod
    def request_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("La solicitud no puede estar vacía.")
        return value.strip()


class JobResume(BaseModel):
    mode: Literal["resume_session", "retry_step"]


class JobDispatch(BaseModel):
    agent: Literal["claude", "codex", "antigravity"] | None = None
    model: str | None = Field(default=None, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")
    version: int = Field(ge=0)


class ApprovalDecision(BaseModel):
    decision: Literal["approve", "reject"]
    scope: Literal["once", "job"] = "once"
    reason: str | None = Field(default=None, max_length=4000)


class RepositoryCreate(BaseModel):
    mode: Literal["register", "create"]
    name: str = Field(min_length=1, max_length=64)
    path: str | None = Field(default=None, max_length=4096)
    default_branch: str | None = Field(default=None, max_length=255)
    check_commands: list[dict[str, Any]] = Field(default_factory=list, max_length=32)
