"""install_autostart.py 的 dry-run 分支选择回归测试。

修复背景：main() 原先写成 `if not args.dry_run and _systemd_available()`，
导致 --dry-run 时即使检测到 systemd 也会错误回退到 crontab，预览不到
systemd 路径命令。以下用例锁定 dry-run 下仍应按 systemd 可用性选择分支。
"""

import pytest

import install_autostart


def _patch_posix(monkeypatch: pytest.MonkeyPatch, systemd_available: bool):
    """把入口固定为 POSIX，并替换 systemd 可用性探测。"""
    monkeypatch.setattr(install_autostart.os, "name", "posix")
    monkeypatch.setattr(install_autostart, "_systemd_available", lambda: systemd_available)


def test_dry_run_with_systemd_prefers_systemd(monkeypatch: pytest.MonkeyPatch) -> None:
    """--dry-run 且检测到 systemd 时，应进入 systemd 分支而不是 crontab。"""
    _patch_posix(monkeypatch, systemd_available=True)
    calls = []

    def fake_systemd(args):
        calls.append("systemd")
        return 0

    monkeypatch.setattr(install_autostart, "_install_systemd", fake_systemd)

    def fake_crontab(args):
        raise AssertionError("dry-run + systemd 不应回退 crontab")

    monkeypatch.setattr(install_autostart, "_install_crontab", fake_crontab)
    monkeypatch.setattr(install_autostart.sys, "argv", ["install_autostart.py", "--dry-run"])

    rc = install_autostart.main()
    assert rc == 0
    assert calls == ["systemd"]


def test_dry_run_without_systemd_falls_back_to_crontab(monkeypatch: pytest.MonkeyPatch) -> None:
    """--dry-run 且未检测到 systemd 时，仍应回退 crontab。"""
    _patch_posix(monkeypatch, systemd_available=False)
    calls = []

    def fake_systemd(args):
        raise AssertionError("无 systemd 时不应进入 systemd 分支")

    monkeypatch.setattr(install_autostart, "_install_systemd", fake_systemd)

    def fake_crontab(args):
        calls.append("crontab")
        return 0

    monkeypatch.setattr(install_autostart, "_install_crontab", fake_crontab)
    monkeypatch.setattr(install_autostart.sys, "argv", ["install_autostart.py", "--dry-run"])

    rc = install_autostart.main()
    assert rc == 0
    assert calls == ["crontab"]
