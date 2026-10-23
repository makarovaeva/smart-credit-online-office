import json

import yaml
from openapi_spec_validator import validate

from app.main import app
from scripts.export_openapi import JSON_OUTPUT, YAML_OUTPUT


def test_spec_is_valid_openapi() -> None:
    validate(app.openapi())


def test_exported_spec_is_up_to_date() -> None:
    """Если упал - перегенерируй: uv run python -m scripts.export_openapi"""
    spec = app.openapi()
    assert json.loads(JSON_OUTPUT.read_text()) == spec
    assert yaml.safe_load(YAML_OUTPUT.read_text()) == spec
