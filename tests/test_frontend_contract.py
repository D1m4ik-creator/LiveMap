"""Keep the browser's endpoint manifest aligned with the running OpenAPI contract.

The integration suite exercises the public and admin responses against a temporary
PostGIS database. This check catches route/method/schema drift before that flow is
opened in a browser.
"""

import json
import re
from pathlib import Path

from livemap.api.app import app
from livemap.core.config import ROOT_DIR


def _response_references(schema: dict) -> set[str]:
    refs = set()
    if "$ref" in schema:
        refs.add(schema["$ref"].rsplit("/", 1)[-1])
    for value in schema.values():
        if isinstance(value, dict):
            refs.update(_response_references(value))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, dict):
                    refs.update(_response_references(item))
    return refs


def test_frontend_routes_match_openapi() -> None:
    frontend = ROOT_DIR / "frontend" / "src" / "api"
    routes = json.loads((frontend / "routes.json").read_text(encoding="utf-8"))
    client = (frontend / "client.ts").read_text(encoding="utf-8")
    openapi = app.openapi()
    referenced = set(re.findall(r"endpoint\('([A-Za-z]+)'", client))
    assert referenced == set(routes), "Client and endpoint manifest must use the same routes"
    for name, entry in routes.items():
        path = entry["path"]
        assert path.startswith("/api/v1/"), name
        assert path in openapi["paths"], (name, path)
        for method in entry["methods"]:
            operation = openapi["paths"][path].get(method)
            assert operation is not None, (name, method)
            success = [response for code, response in operation["responses"].items() if code.startswith("2")]
            assert success, (name, method)
            if "response" in entry and method != "delete":
                refs = set().union(*(
                    _response_references(response.get("content", {}).get("application/json", {}).get("schema", {}))
                    for response in success
                ))
                assert entry["response"] in refs, (name, method, refs)
