import json
import re

from app.main import app
from scripts.export_postman import (
    COLLECTION_OUTPUT,
    ENVIRONMENT_OUTPUT,
    build_collection,
    build_environment,
    render,
)


def _requests(items: list[dict]) -> list[dict]:
    result = []
    for item in items:
        result += _requests(item["item"]) if "item" in item else [item["request"]]
    return result


def _pattern(path: str) -> str:
    return re.sub(r"\{[^/]+\}", "*", path)


def test_exported_collection_is_up_to_date() -> None:
    """Если упал - перегенерируй: uv run python -m scripts.export_postman"""
    assert COLLECTION_OUTPUT.read_text() == render(build_collection())
    assert ENVIRONMENT_OUTPUT.read_text() == render(build_environment())


def test_every_request_exists_in_openapi() -> None:
    spec = {
        (method.upper(), _pattern(path.removeprefix("/api/v1")))
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    }
    collection = json.loads(COLLECTION_OUTPUT.read_text())
    for request in _requests(collection["item"]):
        path = "/" + "/".join(request["url"]["path"])
        # Переменные Postman {{applicationId}} -> параметры пути
        key = (request["method"], _pattern(path.replace("{{", "{").replace("}}", "}")))
        assert key in spec, f"{key} нет в OpenAPI"
