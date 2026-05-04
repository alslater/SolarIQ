from pathlib import Path
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

import solariq.auth as auth_module

from solariq.auth import (
    LOCKOUT_ERROR,
    authenticate_user,
    change_password,
    create_initial_user,
    create_session,
    create_user,
    create_user_as_admin,
    delete_user_as_admin,
    delete_user,
    get_session_user,
    has_admin_users,
    has_users,
    init_auth_db,
    invalidate_session,
    list_users,
    list_users_with_roles,
    promote_user_to_admin,
    set_user_admin_role_as_admin,
)


def _db_path(tmp_path: Path) -> str:
    return str(tmp_path / "auth.sqlite3")


def test_init_and_first_user_bootstrap(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)

    assert has_users(db_path) is False
    first = create_initial_user(db_path, "Admin", "strong-pass-1")

    assert first.username == "admin"
    assert first.is_admin is True
    assert has_users(db_path) is True


def test_create_initial_user_fails_once_users_exist(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)

    first = create_initial_user(db_path, "Admin", "strong-pass-1")
    assert first.is_admin is True

    with pytest.raises(ValueError, match="already exists. Please sign in"):
        create_initial_user(db_path, "OtherAdmin", "strong-pass-2")

    rows = list_users_with_roles(db_path)
    assert rows == [{"username": "admin", "is_admin": True}]


def test_authenticate_and_session_round_trip(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    user = create_user(db_path, "alice", "strong-pass-1")

    assert authenticate_user(db_path, "alice", "wrong") is None
    logged_in = authenticate_user(db_path, "alice", "strong-pass-1")
    assert logged_in is not None

    token = create_session(db_path, user.id)
    session_user = get_session_user(db_path, token)
    assert session_user is not None
    assert session_user.username == "alice"

    invalidate_session(db_path, token)
    assert get_session_user(db_path, token) is None


def test_admin_can_create_and_delete_users(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "admin", "strong-pass-1")

    create_user_as_admin(db_path, "admin", "bob", "strong-pass-2")
    assert list_users(db_path) == ["admin", "bob"]

    delete_user_as_admin(db_path, "admin", "bob")
    assert list_users(db_path) == ["admin"]


def test_cannot_delete_last_user(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "admin", "strong-pass-1")

    with pytest.raises(ValueError, match="last user"):
        delete_user_as_admin(db_path, "admin", "admin")


def test_change_password(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "admin", "strong-pass-1")

    with pytest.raises(ValueError, match="Current password"):
        change_password(db_path, "admin", "bad", "strong-pass-2")

    change_password(db_path, "admin", "strong-pass-1", "strong-pass-2")
    assert authenticate_user(db_path, "admin", "strong-pass-1") is None
    assert authenticate_user(db_path, "admin", "strong-pass-2") is not None


def test_cannot_delete_last_admin_even_with_multiple_users(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "admin", "strong-pass-1")
    create_user_as_admin(db_path, "admin", "user1", "strong-pass-2")

    with pytest.raises(ValueError, match="last administrator"):
        delete_user_as_admin(db_path, "admin", "admin")


def test_promote_user_to_admin_recovery(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "admin", "strong-pass-1")
    create_user_as_admin(db_path, "admin", "user1", "strong-pass-2")

    # Simulate a broken historical state where no admins remain.
    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE users SET is_admin = 0")
    assert has_admin_users(db_path) is False

    promoted = promote_user_to_admin(db_path, "user1")
    assert promoted.is_admin is True
    assert has_admin_users(db_path) is True


def test_admin_can_create_admin_user_and_roles_are_listed(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "admin", "strong-pass-1")

    created = create_user_as_admin(
        db_path,
        "admin",
        "ops",
        "strong-pass-2",
        is_admin=True,
    )
    assert created.is_admin is True

    rows = list_users_with_roles(db_path)
    assert rows == [
        {"username": "admin", "is_admin": True},
        {"username": "ops", "is_admin": True},
    ]


def test_admin_can_promote_and_demote_user_role(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "admin", "strong-pass-1")
    create_user_as_admin(db_path, "admin", "alice", "strong-pass-2")

    promoted = set_user_admin_role_as_admin(db_path, "admin", "alice", is_admin=True)
    assert promoted.is_admin is True

    demoted = set_user_admin_role_as_admin(db_path, "admin", "alice", is_admin=False)
    assert demoted.is_admin is False


def test_cannot_demote_last_admin(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "admin", "strong-pass-1")

    with pytest.raises(ValueError, match="last administrator"):
        set_user_admin_role_as_admin(db_path, "admin", "admin", is_admin=False)


def test_password_requires_three_character_classes(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)

    with pytest.raises(ValueError, match="at least 3 of"):
        create_user(db_path, "weak", "alllowercase")

    created = create_user(db_path, "valid", "Abcdefg1")
    assert created.username == "valid"


def test_authenticate_user_locks_after_repeated_failures(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "alice", "Strongpass1!")

    for _ in range(5):
        assert authenticate_user(db_path, "alice", "wrong-pass") is None

    with pytest.raises(ValueError, match="Too many failed sign-in attempts"):
        authenticate_user(db_path, "alice", "Strongpass1!")


def test_successful_login_clears_failed_attempts(tmp_path):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "alice", "Strongpass1!")

    for _ in range(4):
        assert authenticate_user(db_path, "alice", "wrong-pass") is None

    assert authenticate_user(db_path, "alice", "Strongpass1!") is not None

    for _ in range(4):
        assert authenticate_user(db_path, "alice", "wrong-pass") is None

    assert authenticate_user(db_path, "alice", "Strongpass1!") is not None


def test_lockout_expires_after_five_minutes(tmp_path, monkeypatch):
    db_path = _db_path(tmp_path)
    init_auth_db(db_path)
    create_user(db_path, "alice", "Strongpass1!")

    base_time = datetime(2026, 5, 4, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(auth_module, "_utcnow", lambda: base_time)

    for _ in range(5):
        assert authenticate_user(db_path, "alice", "wrong-pass") is None

    with pytest.raises(ValueError, match=LOCKOUT_ERROR):
        authenticate_user(db_path, "alice", "Strongpass1!")

    monkeypatch.setattr(auth_module, "_utcnow", lambda: base_time + timedelta(minutes=5, seconds=1))

    assert authenticate_user(db_path, "alice", "Strongpass1!") is not None
