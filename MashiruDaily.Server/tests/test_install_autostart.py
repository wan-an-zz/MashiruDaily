"""install_autostart.py 的分支选择契约测试（全部 mock，不执行真实进程）。

- dry-run 回归：main() 原先写成 `if not args.dry_run and _systemd_available()`，
  导致 --dry-run 时即使检测到 systemd 也会错误回退到 crontab，预览不到
  systemd 路径命令。以下用例锁定 dry-run 下仍应按 systemd 可用性选择分支。
- Windows 分支：非管理员（且非演练）不自动 UAC 提权，改为打印手动操作指引，
  并以退出码 2（EXIT_MANUAL_REQUIRED）退出；管理员与 dry-run 直接进入执行分支。
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


# ---------------------------------------------------------------------------
# Windows 分支：非管理员打印手动指引（退出码 2），不再自动 UAC 提权
# ---------------------------------------------------------------------------


def _patch_windows(monkeypatch: pytest.MonkeyPatch, is_admin: bool) -> None:
    """把入口固定为 Windows，并替换管理员判定。"""
    monkeypatch.setattr(install_autostart.os, "name", "nt")
    monkeypatch.setattr(install_autostart, "_is_admin_win", lambda: is_admin)


def test_windows_non_admin_prints_manual_guidance_and_returns_2(monkeypatch, capsys) -> None:
    """Windows 非管理员 + 默认注册模式：不执行注册、不自动提权，打印手动指引并返回退出码 2。"""
    _patch_windows(monkeypatch, is_admin=False)

    def fake_windows(args):
        raise AssertionError("非管理员不应执行 _install_windows")

    monkeypatch.setattr(install_autostart, "_install_windows", fake_windows)
    monkeypatch.setattr(install_autostart.sys, "argv", ["install_autostart.py"])

    rc = install_autostart.main()
    assert rc == install_autostart.EXIT_MANUAL_REQUIRED
    out = capsys.readouterr().out
    assert "管理员" in out
    assert "install_autostart.py" in out
    assert "1)" in out
    assert "2)" in out


def test_windows_non_admin_uninstall_keeps_flag_in_guidance(monkeypatch, capsys) -> None:
    """Windows 非管理员 + --uninstall：手动指引中的重跑命令应保留 --uninstall。"""
    _patch_windows(monkeypatch, is_admin=False)
    monkeypatch.setattr(install_autostart, "_install_windows", lambda args: 0)
    monkeypatch.setattr(install_autostart.sys, "argv", ["install_autostart.py", "--uninstall"])

    rc = install_autostart.main()
    assert rc == install_autostart.EXIT_MANUAL_REQUIRED
    assert "--uninstall" in capsys.readouterr().out


def test_windows_admin_runs_install(monkeypatch) -> None:
    """Windows 管理员：直接进入 _install_windows，无手动指引。"""
    _patch_windows(monkeypatch, is_admin=True)
    calls = []

    def fake_windows(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(install_autostart, "_install_windows", fake_windows)
    monkeypatch.setattr(install_autostart.sys, "argv", ["install_autostart.py"])

    rc = install_autostart.main()
    assert rc == 0
    assert len(calls) == 1
    assert calls[0].uninstall is False


def test_windows_non_admin_dry_run_allowed(monkeypatch) -> None:
    """Windows 非管理员 + --dry-run：演练无需管理员，仍进入 _install_windows 打印命令。"""
    _patch_windows(monkeypatch, is_admin=False)
    calls = []

    def fake_windows(args):
        calls.append(args)
        return 0

    monkeypatch.setattr(install_autostart, "_install_windows", fake_windows)
    monkeypatch.setattr(install_autostart.sys, "argv", ["install_autostart.py", "--dry-run"])

    rc = install_autostart.main()
    assert rc == 0
    assert len(calls) == 1
