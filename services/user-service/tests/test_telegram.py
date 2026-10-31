import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from user_service.application.telegram import InvalidInitData, validate_init_data

TEST_BOT_TOKEN = "unit-test-only-not-a-real-bot"
NOW = 1793390000


def signed(fields: dict[str, str]) -> str:
    data = "\n".join(f"{key}={fields[key]}" for key in sorted(fields))
    key = hmac.new(b"WebAppData", TEST_BOT_TOKEN.encode(), hashlib.sha256).digest()
    signature = hmac.new(key, data.encode(), hashlib.sha256).hexdigest()
    return urlencode({**fields, "hash": signature})


def fields() -> dict[str, str]:
    return {
        "auth_date": str(NOW),
        "user": json.dumps(
            {"id": 1234567890123, "first_name": "Иван", "last_name": "Иванов", "username": "ivan"}
        ),
    }


def test_valid_unicode_identity_and_large_telegram_id() -> None:
    identity = validate_init_data(signed(fields()), TEST_BOT_TOKEN, now=NOW)
    assert identity.telegram_id == 1234567890123
    assert identity.full_name == "Иван Иванов"
    assert identity.username == "ivan"


def test_signed_optional_signature_field_is_included_in_hmac() -> None:
    values = {**fields(), "signature": "illustrative-third-party-signature"}
    assert validate_init_data(signed(values), TEST_BOT_TOKEN, now=NOW).telegram_id > 0


@pytest.mark.parametrize("raw", ["", "not-a-query", "hash=", "x=%XX", "x=%ff", "a=1&a=2"])
def test_malformed_data_is_rejected(raw: str) -> None:
    with pytest.raises(InvalidInitData):
        validate_init_data(raw, TEST_BOT_TOKEN, now=NOW)


def test_tampering_and_duplicate_fields_are_rejected() -> None:
    raw = signed(fields())
    for candidate in [
        raw + "&auth_date=1",
        raw.replace("auth_date=1793390000", "auth_date=1793390001"),
        raw + "&hash=" + "0" * 64,
    ]:
        with pytest.raises(InvalidInitData):
            validate_init_data(candidate, TEST_BOT_TOKEN, now=NOW)


@pytest.mark.parametrize("offset", [-301, 31])
def test_expired_and_future_data_are_rejected(offset: int) -> None:
    values = {**fields(), "auth_date": str(NOW + offset)}
    with pytest.raises(InvalidInitData):
        validate_init_data(signed(values), TEST_BOT_TOKEN, now=NOW)


@pytest.mark.parametrize(
    "identity",
    [
        {"id": True, "first_name": "A"},
        {"id": -1, "first_name": "A"},
        {"id": 2**63, "first_name": "A"},
        {"id": 1, "first_name": " "},
        {"id": 1, "first_name": "A", "last_name": 7},
        [],
    ],
)
def test_invalid_signed_user_data_is_rejected(identity: object) -> None:
    values = {**fields(), "user": json.dumps(identity)}
    with pytest.raises(InvalidInitData):
        validate_init_data(signed(values), TEST_BOT_TOKEN, now=NOW)
