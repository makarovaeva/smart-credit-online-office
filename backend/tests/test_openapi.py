import json
from pathlib import Path

from app.main import app

EXPORTED = Path(__file__).resolve().parents[2] / "docs" / "api" / "openapi.json"


def test_openapi_builds() -> None:
    schema = app.openapi()
    assert "/api/v1/applications/{application_id}/submit" in schema["paths"]


def test_exported_spec_is_up_to_date() -> None:
    """Если упал - перегенерируй: uv run python -m scripts.export_openapi"""
    assert json.loads(EXPORTED.read_text()) == app.openapi()
