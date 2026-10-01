from auth.users_db import (
    authenticate, create_user, delete_user, init_users_db, list_users, seed_default_users,
)


def test_create_and_authenticate(tmp_path):
    db = tmp_path / "users.db"
    init_users_db(db)
    create_user("alice", "supersecret123", "operator", db)
    assert authenticate("alice", "supersecret123", db) == "operator"


def test_wrong_password_rejected(tmp_path):
    db = tmp_path / "users.db"
    init_users_db(db)
    create_user("alice", "supersecret123", "operator", db)
    assert authenticate("alice", "wrongpass", db) is None


def test_unknown_user_rejected(tmp_path):
    db = tmp_path / "users.db"
    init_users_db(db)
    assert authenticate("nobody", "whatever", db) is None


def test_duplicate_username_rejected(tmp_path):
    db = tmp_path / "users.db"
    init_users_db(db)
    create_user("alice", "supersecret123", "operator", db)
    try:
        create_user("alice", "anotherpass123", "admin", db)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_invalid_role_rejected(tmp_path):
    db = tmp_path / "users.db"
    init_users_db(db)
    try:
        create_user("bob", "validpass123", "superadmin", db)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_short_password_rejected(tmp_path):
    db = tmp_path / "users.db"
    init_users_db(db)
    try:
        create_user("carol", "short", "viewer", db)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_seed_default_users_only_on_empty_table(tmp_path):
    db = tmp_path / "users.db"
    init_users_db(db)
    seed_default_users(db)
    assert len(list_users(db)) == 3
    assert authenticate("admin", "admin12345", db) == "admin"
    assert authenticate("operator", "operator12345", db) == "operator"
    assert authenticate("viewer", "viewer12345", db) == "viewer"
    seed_default_users(db)  # must be a no-op the second time
    assert len(list_users(db)) == 3


def test_delete_user(tmp_path):
    db = tmp_path / "users.db"
    init_users_db(db)
    create_user("alice", "supersecret123", "viewer", db)
    assert delete_user("alice", db) is True
    assert delete_user("alice", db) is False
    assert authenticate("alice", "supersecret123", db) is None
