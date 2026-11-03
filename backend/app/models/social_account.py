from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    JSON,
    String,
    Text,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.models.user import utc_now


class SocialAccount(Base):
    __tablename__ = "social_accounts"
    __table_args__ = (
        CheckConstraint(
            "platform IN ('facebook_page', 'instagram')",
            name="ck_social_account_platform",
        ),
        CheckConstraint(
            "connection_status IN ('connected', 'expired', 'revoked', 'error', 'disconnected')",
            name="ck_social_account_connection_status",
        ),
        Index(
            "uq_social_account_workspace_platform_id",
            "workspace_id",
            "platform",
            "platform_account_id",
            unique=True,
        ),
        Index("ix_social_accounts_workspace_status", "workspace_id", "connection_status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL")
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_account_id: Mapped[str] = mapped_column(String(255), nullable=False)
    username: Mapped[str | None] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    profile_image_url: Mapped[str | None] = mapped_column(String(2048))
    account_type: Mapped[str | None] = mapped_column(String(64))
    parent_account_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("social_accounts.id", ondelete="SET NULL")
    )
    connection_status: Mapped[str] = mapped_column(
        String(32), default="connected", nullable=False
    )
    granted_scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    connected_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    connected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    credential: Mapped[SocialAccountCredential | None] = relationship(
        back_populates="social_account",
        cascade="all, delete-orphan",
        uselist=False,
    )
    parent_account: Mapped[SocialAccount | None] = relationship(
        remote_side="SocialAccount.id",
        back_populates="child_accounts",
    )
    child_accounts: Mapped[list[SocialAccount]] = relationship(back_populates="parent_account")


class SocialAccountCredential(Base):
    __tablename__ = "social_account_credentials"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    social_account_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("social_accounts.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    encrypted_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text)
    token_type: Mapped[str] = mapped_column(String(32), default="bearer", nullable=False)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    refresh_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    encryption_version: Mapped[int] = mapped_column(default=1, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    social_account: Mapped[SocialAccount] = relationship(back_populates="credential")


class MetaAuthorization(Base):
    __tablename__ = "meta_authorizations"
    __table_args__ = (
        Index(
            "uq_meta_authorization_workspace_user",
            "workspace_id",
            "authorized_by",
            unique=True,
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    authorized_by: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    meta_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    encrypted_user_access_token: Mapped[str] = mapped_column(Text, nullable=False)
    granted_scopes: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    access_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )


class OAuthState(Base):
    __tablename__ = "oauth_states"
    __table_args__ = (
        CheckConstraint("provider = 'meta'", name="ck_oauth_state_provider"),
        Index("ix_oauth_states_expiry", "expires_at"),
    )

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    workspace_id: Mapped[UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
    )
    brand_id: Mapped[UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("brands.id", ondelete="SET NULL")
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
