import json
from pathlib import Path

from user_service.main import create_app


def test_openapi_matches_committed_contract() -> None:
    root = Path(__file__).resolve().parents[3]
    expected = json.loads((root / "packages/contracts/openapi/user-service.v1.json").read_text())
    assert create_app().openapi() == expected
