from __future__ import annotations

from app import disk_security


def test_disk_encryption_status_is_read_only_and_platform_bounded(monkeypatch) -> None:
    monkeypatch.setattr(disk_security.platform, "system", lambda: "Plan9")

    status = disk_security.disk_encryption_status()

    assert status == {"platform": "plan9", "status": "unsupported", "provider": None}


def test_windows_access_denied_is_explicitly_reported(monkeypatch) -> None:
    class Result:
        returncode = 1
        stdout = ""
        stderr = "Access is denied"

    monkeypatch.setattr(disk_security.platform, "system", lambda: "Windows")
    monkeypatch.setattr(disk_security.subprocess, "run", lambda *args, **kwargs: Result())
    disk_security._STATUS_CACHE.clear()

    status = disk_security.disk_encryption_status()

    assert status["status"] == "unknown"
    assert status["reason"] == "administrator_required"


def test_chinese_bitlocker_status_is_detected(monkeypatch) -> None:
    class Result:
        returncode = 0
        stdout = "转换状态: 仅加密了已用空间\n已加密百分比: 100.0%\n保护状态: 保护已启用"
        stderr = ""

    monkeypatch.setattr(disk_security.platform, "system", lambda: "Windows")
    monkeypatch.setattr(disk_security.subprocess, "run", lambda *args, **kwargs: Result())
    disk_security._STATUS_CACHE.clear()

    status = disk_security.disk_encryption_status()

    assert status["status"] == "enabled"
