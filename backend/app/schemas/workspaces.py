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


class InvitationCreate(BaseModel):
    email: EmailStr
    role: WorkspaceRole = WorkspaceRole.MEMBER


class InvitationRead(BaseModel):
    id: UUID
    email: str
    role: WorkspaceRole
    status: str
    email_sent: bool
    created_at: datetime
    expires_at: datetime


class InvitationCreated(InvitationRead):
    # Returned once, to the admin who created it, so the link can be passed on
    # by hand when email is off or failed. It is not stored and cannot be read again.
    invite_url: str
    email_error: str | None = None


class InvitationPreview(BaseModel):
    workspace_name: str
    email: str
    role: WorkspaceRole
    expires_at: datetime


class InvitationAccepted(BaseModel):
    workspace_id: UUID
    role: WorkspaceRole
