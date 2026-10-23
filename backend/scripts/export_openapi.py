"""Выгрузка OpenAPI-спецификации в docs/api/openapi.json.

Запуск из backend/: uv run python -m scripts.export_openapi
"""

import json
from pathlib import Path

from app.main import app

OUTPUT = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def main() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n")
    print(f"written {OUTPUT}")


if __name__ == "__main__":
    main()
