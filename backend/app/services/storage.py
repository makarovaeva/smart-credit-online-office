"""Файловое хранилище документов: локальный каталог DOCUMENT_STORAGE_DIR.

Ключ - относительный путь, его формирует только backend (имя файла клиента в путь не попадает).
"""

import os
import uuid
from pathlib import Path

from app.core.config import get_settings


def _root() -> Path:
    return Path(get_settings().document_storage_dir).resolve()


def path_for(key: str) -> Path:
    path = (_root() / key).resolve()
    if not path.is_relative_to(_root()):
        raise ValueError(f"storage key вне хранилища: {key}")
    return path


def save(key: str, content: bytes) -> None:
    """Пишет во временный файл и переименовывает: недописанный файл не виден по ключу."""
    path = path_for(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)


def delete(key: str) -> None:
    path_for(key).unlink(missing_ok=True)
