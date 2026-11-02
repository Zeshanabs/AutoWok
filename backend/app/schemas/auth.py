from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    password: str = Field(min_length=12, max_length=128)

    @field_validator("full_name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Full name must contain at least two characters.")
        return normalized

    @field_validator("password")
    @classmethod
    def validate_password(cls, value: str) -> str:
        if (
            len(value) < 12
            or not any(character.islower() for character in value)
            or not any(character.isupper() for character in value)
            or not any(character.isdigit() for character in value)
            or not any(not character.isalnum() for character in value)
        ):
            raise ValueError(
                "Password must be at least 12 characters and include uppercase, lowercase, "
                "a number, and a symbol."
            )
        return value


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class UserRead(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    is_active: bool
    is_verified: bool


class WorkspaceRead(BaseModel):
    id: UUID
    name: str
    slug: str
    role: str


class CurrentSessionRead(BaseModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    last_used_at: datetime


class RegistrationResponse(BaseModel):
    user: UserRead
    workspace: WorkspaceRead


class CurrentUserResponse(BaseModel):
    user: UserRead
    session: CurrentSessionRead
    workspaces: list[WorkspaceRead]
    selected_workspace: WorkspaceRead | None


class SessionRead(BaseModel):
    id: UUID
    created_at: datetime
    last_used_at: datetime
    expires_at: datetime
    device_label: str
    is_current: bool
