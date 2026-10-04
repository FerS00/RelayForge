from __future__ import annotations

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
