"""Выгрузка OpenAPI-спецификации в docs/api/openapi.json и docs/api/openapi.yaml.

Запуск из backend/: uv run python -m scripts.export_openapi
"""

import json
from pathlib import Path

import yaml

from app.main import app

API_DOCS = Path(__file__).resolve().parents[2] / "docs" / "api"
JSON_OUTPUT = API_DOCS / "openapi.json"
YAML_OUTPUT = API_DOCS / "openapi.yaml"


def render_json(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False, indent=2) + "\n"


class _Dumper(yaml.SafeDumper):
    """Многострочные описания - блоком «|», а не строкой в кавычках."""


def _str(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_Dumper.add_representer(str, _str)


def render_yaml(spec: dict) -> str:
    return yaml.dump(spec, Dumper=_Dumper, allow_unicode=True, sort_keys=False, width=100)


def main() -> None:
    spec = app.openapi()
    API_DOCS.mkdir(parents=True, exist_ok=True)
    JSON_OUTPUT.write_text(render_json(spec))
    YAML_OUTPUT.write_text(render_yaml(spec))
    print(f"written {JSON_OUTPUT} and {YAML_OUTPUT}")


if __name__ == "__main__":
    main()
