"""Storage abstraction for uploaded media.

Callers work with opaque *storage keys* (for example
``workspaces/<id>/media/<uuid>.jpg``), never with filesystem paths supplied by
users. ``LocalStorageService`` is the development backend; an object-storage
backend can implement the same ``StorageBackend`` protocol later.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Protocol

from app.core.config import get_settings

settings = get_settings()

_SAFE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,511}$")


class StorageError(RuntimeError):
    """Raised when media cannot be stored or retrieved."""


class StorageBackend(Protocol):
    provider_name: str

    def save_file(self, key: str, data: bytes) -> None: ...

    def read_file(self, key: str) -> bytes: ...

    def exists(self, key: str) -> bool: ...

    def delete_file(self, key: str) -> None: ...

    def local_path(self, key: str) -> Path | None: ...


def validate_storage_key(key: str) -> str:
    if not _SAFE_KEY.fullmatch(key) or ".." in key.split("/") or "//" in key:
        raise StorageError("Invalid storage key.")
    return key


class LocalStorageService:
    provider_name = "local"

    def __init__(self, base_path: str | None = None) -> None:
        self.base_path = Path(base_path or settings.local_storage_path).resolve()
        self.base_path.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, key: str) -> Path:
        validate_storage_key(key)
        path = (self.base_path / key).resolve()
        if self.base_path not in path.parents:
            raise StorageError("Invalid storage key.")
        return path

    def local_path(self, key: str) -> Path | None:
        return self.resolve_path(key)

    def save_file(self, key: str, data: bytes) -> None:
        path = self.resolve_path(key)
        tmp_path = path.with_name(f".{path.name}.partial")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with tmp_path.open("wb") as handle:
                handle.write(data)
            tmp_path.replace(path)
        except OSError as exc:
            tmp_path.unlink(missing_ok=True)
            raise StorageError("The file could not be stored.") from exc

    def read_file(self, key: str) -> bytes:
        try:
            return self.resolve_path(key).read_bytes()
        except OSError as exc:
            raise StorageError("The stored file could not be read.") from exc

    def exists(self, key: str) -> bool:
        try:
            return self.resolve_path(key).is_file()
        except StorageError:
            return False

    def delete_file(self, key: str) -> None:
        try:
            self.resolve_path(key).unlink(missing_ok=True)
        except OSError as exc:
            raise StorageError("The stored file could not be deleted.") from exc


storage_service: StorageBackend = LocalStorageService()
