import pytest

from user_service.application.passwords import hash_password, normalize_login, password_hash


def test_passwords_are_salted_argon2_hashes() -> None:
    password = "unit-test-only-long-password"
    first, second = hash_password(password), hash_password(password)
    assert first.startswith("$argon2id$")
    assert first != second and password not in first
    assert password_hash.verify(password, first)
    assert not password_hash.verify("wrong", first)


@pytest.mark.parametrize("password", ["short", "x" * 129])
def test_password_length_is_enforced(password: str) -> None:
    with pytest.raises(ValueError):
        hash_password(password)


def test_login_normalization() -> None:
    assert normalize_login("  Chef.Test  ") == "chef.test"
    with pytest.raises(ValueError):
        normalize_login("a/b")
