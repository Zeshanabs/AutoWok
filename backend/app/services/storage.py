from __future__ import annotations

from pathlib import Path

from app.core.config import get_settings

settings = get_settings()


class LocalStorageService:
    def __init__(self, base_path: str | None = None) -> None:
        self.base_path = Path(base_path or settings.local_storage_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, relative_path: str) -> Path:
        return (self.base_path / relative_path).resolve()


storage_service = LocalStorageService()
