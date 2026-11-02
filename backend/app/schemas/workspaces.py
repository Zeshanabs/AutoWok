from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator


class WorkspaceRole(StrEnum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Workspace name must contain at least two characters.")
        return normalized


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=2, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if len(normalized) < 2:
            raise ValueError("Workspace name must contain at least two characters.")
        return normalized


class WorkspaceMemberAdd(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.MEMBER


class WorkspaceRoleUpdate(BaseModel):
    role: WorkspaceRole


class WorkspaceDetail(BaseModel):
    id: UUID
    name: str
    slug: str
    owner_id: UUID
    created_at: datetime
    updated_at: datetime


class WorkspaceMemberRead(BaseModel):
    user_id: UUID
    full_name: str
    email: str
    role: WorkspaceRole
    joined_at: datetime
