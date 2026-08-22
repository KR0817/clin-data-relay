from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.centre_profile import CentreProfile, CentreProfileError, load_centre_profile
from app.main import create_app
from app.persistence import Database
from app.security import SETUP_REQUIRED_PASSWORD_HASH, password_hash


def profile_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "profile_type": "clinical-edc-centre-lite",
        "profile_version": 1,
        "centre_code": "SITE_A",
        "username": "site-a@example.test",
    }
    payload.update(overrides)
    return payload


def test_centre_profile_parser_accepts_only_the_versioned_exact_schema(tmp_path: Path) -> None:
    path = tmp_path / "centre-profile.json"
    path.write_text(json.dumps(profile_payload()), encoding="utf-8")

    profile = load_centre_profile(path)

    assert profile == CentreProfile(centre_code="SITE_A", username="site-a@example.test")
    path.write_text(json.dumps(profile_payload(extra="not-allowed")), encoding="utf-8")
    with pytest.raises(CentreProfileError, match="centre_profile_invalid"):
        load_centre_profile(path)


def test_profile_repository_contains_one_locked_investigator_and_rejects_scope_reuse(tmp_path: Path) -> None:
    profile = CentreProfile(centre_code="SITE_A", username="site-a@example.test")
    database = Database(tmp_path / "centre.db", centre_profile=profile)
    database.initialise()
    with database.connect() as connection:
        users = connection.execute(
            "SELECT username, password_hash, centre_code, role, active FROM users"
        ).fetchall()

    assert len(users) == 1
    assert tuple(users[0]) == (
        "site-a@example.test",
        SETUP_REQUIRED_PASSWORD_HASH,
        "SITE_A",
        "site_investigator",
        1,
    )
    with pytest.raises(RuntimeError, match="centre_profile_database_scope_mismatch"):
        Database(
            database.database_path,
            centre_profile=CentreProfile(centre_code="SITE_B", username="site-b@example.test"),
        ).initialise()


def test_centre_first_run_sets_strong_password_once_and_enables_only_packaged_login(tmp_path: Path) -> None:
    profile = CentreProfile(centre_code="SITE_A", username="site-a@example.test")
    app = create_app(
        database_path=tmp_path / "centre-api.db",
        environment="test",
        product_mode="lite",
        centre_profile=profile,
    )
    with TestClient(app) as client:
        status = client.get("/api/setup/status")
        health = client.get("/api/health")
        assert status.json() == {"required": True, "centre_profile": profile.public_payload()}
        assert health.json()["setup_required"] is True
        assert health.json()["centre_profile"] == profile.public_payload()
        assert client.post(
            "/api/auth/login",
            json={"username": profile.username, "password": "demo-password"},
        ).status_code == 401
        assert client.post(
            "/api/setup/complete",
            json={"password": "weak-password-123", "password_confirmation": "weak-password-123"},
        ).json()["detail"] == "strong_password_required"

        password = "Strong-Random-Password-2026!"
        completed = client.post(
            "/api/setup/complete",
            json={"password": password, "password_confirmation": password},
        )
        assert completed.status_code == 200
        assert completed.json() == {
            "status": "completed",
            "username": profile.username,
            "centre_code": profile.centre_code,
        }
        assert client.get("/api/setup/status").json()["required"] is False
        assert client.post(
            "/api/setup/complete",
            json={"password": password, "password_confirmation": password},
        ).json()["detail"] == "setup_already_completed"
        login = client.post(
            "/api/auth/login",
            json={"username": profile.username, "password": password},
        )
        assert login.status_code == 200
        assert login.json()["user"] == {
            "username": profile.username,
            "centre_code": profile.centre_code,
            "role": "site_investigator",
        }


def test_centre_user_can_configure_kimi_without_the_key_entering_http_responses(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    profile = CentreProfile(centre_code="SITE_A", username="site-a@example.test")
    credential_path = tmp_path / ".runtime" / "kimi-api-key.txt"
    monkeypatch.setenv("KIMI_API_KEY_FILE", str(credential_path))
    monkeypatch.setenv("KIMI_ENABLED", "true")
    monkeypatch.setenv("KIMI_BASE_URL", "https://api.moonshot.cn/v1")
    monkeypatch.setenv("KIMI_MODEL", "kimi-k3")
    app = create_app(
        database_path=tmp_path / "centre-kimi.db",
        environment="test",
        product_mode="lite",
        centre_profile=profile,
    )
    password = "Strong-Random-Password-2026!"
    with TestClient(app) as client:
        client.post(
            "/api/setup/complete",
            json={"password": password, "password_confirmation": password},
        ).raise_for_status()
        login = client.post(
            "/api/auth/login",
            json={"username": profile.username, "password": password},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        missing = client.get("/api/settings/kimi", headers=headers)
        assert missing.json() == {"configured": False, "status": "key_required", "model": "kimi-k3"}
        assert client.put("/api/settings/kimi", headers=headers, json={"key": "too-short"}).status_code == 422

        placeholder_key = "sk-centre-local-placeholder-1234567890"
        configured = client.put(
            "/api/settings/kimi",
            headers=headers,
            json={"key": placeholder_key},
        )
        assert configured.status_code == 200
        assert configured.json() == {"configured": True, "status": "ready", "model": "kimi-k3"}
        assert placeholder_key not in configured.text
        assert credential_path.read_text(encoding="utf-8") == placeholder_key
        assert client.get("/api/health").json()["kimi_integration"] == "ready"


def test_local_centre_password_reset_revokes_sessions_and_rotates_the_hash(tmp_path: Path) -> None:
    profile = CentreProfile(centre_code="SITE_A", username="site-a@example.test")
    database_path = tmp_path / "centre-reset.db"
    database = Database(database_path, centre_profile=profile)
    app = create_app(
        database_path=database_path,
        environment="test",
        product_mode="lite",
        centre_profile=profile,
    )
    old_password = "Old-Strong-Password-2026!"
    new_password = "New-Strong-Password-2026!"
    with TestClient(app) as client:
        client.post(
            "/api/setup/complete",
            json={"password": old_password, "password_confirmation": old_password},
        ).raise_for_status()
        login = client.post(
            "/api/auth/login",
            json={"username": profile.username, "password": old_password},
        )
        old_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        assert client.get("/api/candidates", headers=old_headers).status_code == 200

        Database(database_path, centre_profile=profile).reset_centre_password(password_hash(new_password))

        assert client.get("/api/candidates", headers=old_headers).status_code == 401
        assert client.post(
            "/api/auth/login",
            json={"username": profile.username, "password": old_password},
        ).status_code == 401
        assert client.post(
            "/api/auth/login",
            json={"username": profile.username, "password": new_password},
        ).status_code == 200

    with database.connect() as connection:
        reset_event = connection.execute(
            "SELECT details_json FROM audit_events WHERE event_type = 'centre_password_reset'"
        ).fetchone()
    assert reset_event is not None
    assert "password" not in reset_event["details_json"]
