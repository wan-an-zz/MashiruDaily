"""configure_webhook.py 网关重启降级逻辑的离线契约测试（测试优先，全部 mock）。

面向 configure_webhook._restart_gateway 与 main(argv) 编写（测试优先）：当前
_restart_gateway 尚不存在、main 不接受 argv 参数，用例会以 AttributeError /
TypeError 呈现（预期的 RED 状态），待实现落地后自动转绿。

根因背景（Hermes 源码 NousResearch/hermes-agent hermes_cli/gateway.py
_system_service_identity，L2300-2303）：以 root 运行 `hermes gateway restart`
且网关为 systemd 系统服务时，Hermes 拒绝刷新 systemd 单元并抛未捕获的
ValueError（裸 traceback 进 stderr，退出码 1）；root 下用户级 D-Bus 不可达时
报 "User systemd not reachable"（print_error 写 stdout，退出码 1）。两者均为
配置已成功写入、仅重启动作受限的良性场景，应降级为提示而非失败。
"""

import sys
from pathlib import Path

import pytest

import configure_webhook


class _FakeCompleted:
    """模拟 _config.run_command 的返回对象（CompletedProcess 形状）。"""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ---------------------------------------------------------------------------
# _restart_gateway 函数级用例
# ---------------------------------------------------------------------------


def _monkey_restart(monkeypatch, completed):
    """替换 configure_webhook._config.run_command 为返回预设结果。"""
    calls = []

    def fake_run(cmd, timeout=120):
        calls.append((list(cmd), timeout))
        return completed

    monkeypatch.setattr("configure_webhook._config.run_command", fake_run)
    return calls


def test_restart_success_returns_zero(monkeypatch, capsys) -> None:
    """重启成功（returncode 0）→ 返回 0 并打印 [OK]。"""
    _monkey_restart(monkeypatch, _FakeCompleted(returncode=0))
    rc = configure_webhook._restart_gateway("C:/fake/hermes.exe")
    assert rc == 0
    out = capsys.readouterr().out
    assert "[OK]" in out and "生效" in out


def test_restart_root_refusal_degrades(monkeypatch, capsys) -> None:
    """root 拒绝刷新 systemd 单元（stderr 含 Hermes 拒绝消息）→ 返回 0 并提示下次重启生效。"""
    _monkey_restart(
        monkeypatch,
        _FakeCompleted(
            returncode=1,
            stderr="Traceback (most recent call last):\n"
            'ValueError: Refusing to install the gateway system service as root; '
            "pass --run-as-user root to override (e.g. in LXC containers)\n",
        ),
    )
    rc = configure_webhook._restart_gateway("C:/fake/hermes.exe")
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARN" in out
    assert "config.yaml" in out and "下次重启" in out


def test_restart_user_systemd_unreachable_degrades(monkeypatch, capsys) -> None:
    """root 下用户级 systemd 不可达（stdout 含 User systemd not reachable）→ 返回 0。"""
    _monkey_restart(
        monkeypatch,
        _FakeCompleted(returncode=1, stdout="User systemd not reachable:\n  ..."),
    )
    rc = configure_webhook._restart_gateway("C:/fake/hermes.exe")
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARN" in out


def test_restart_signal_on_stdout_still_degrades(monkeypatch, capsys) -> None:
    """root 拒绝消息出现在 stdout（而非 stderr）也应降级——验证合并流匹配。"""
    _monkey_restart(
        monkeypatch,
        _FakeCompleted(
            returncode=1,
            stdout="Refusing to install the gateway system service as root; "
            "pass --run-as-user root to override (e.g. in LXC containers)\n",
        ),
    )
    rc = configure_webhook._restart_gateway("C:/fake/hermes.exe")
    assert rc == 0
    assert "WARN" in capsys.readouterr().out


def test_restart_unrelated_failure_still_fails(monkeypatch, capsys) -> None:
    """无关失败（stderr 不含两个信号）→ 保持返回 1 并打印非零警告（走 stderr）。"""
    _monkey_restart(
        monkeypatch,
        _FakeCompleted(returncode=1, stderr="systemctl: command not found\n"),
    )
    rc = configure_webhook._restart_gateway("C:/fake/hermes.exe")
    assert rc == 1
    err = capsys.readouterr().err
    assert "警告" in err and "非零退出码" in err


def test_restart_rootish_but_not_signal_still_fails(monkeypatch) -> None:
    """提到 root/systemd 但不是 Hermes 拒绝信号的失败 → 返回 1（防过度匹配）。"""
    _monkey_restart(
        monkeypatch,
        _FakeCompleted(
            returncode=1,
            stderr="Permission denied: root cannot connect to systemd\n",
        ),
    )
    rc = configure_webhook._restart_gateway("C:/fake/hermes.exe")
    assert rc == 1


def test_restart_timeout_returns_one(monkeypatch) -> None:
    """run_command 抛 TimeoutError（subprocess.TimeoutExpired 是其子类）→ 返回 1。"""
    def fake_run(cmd, timeout=120):
        raise TimeoutError("command timed out")

    monkeypatch.setattr("configure_webhook._config.run_command", fake_run)
    rc = configure_webhook._restart_gateway("C:/fake/hermes.exe")
    assert rc == 1


# ---------------------------------------------------------------------------
# main(argv) 集成级用例（真实 config 读写链，仅 mock 外部依赖）
# ---------------------------------------------------------------------------


def _config_chain(monkeypatch, tmp_path: Path):
    """把 configure_webhook 的外部依赖指向 tmp：config.yaml 存在、hermes 可执行文件可定位。"""
    cfg = tmp_path / "config.yaml"
    cfg.write_text("platforms:\n  qqbot:\n    enabled: true\n", encoding="utf-8")
    monkeypatch.setattr("configure_webhook._config.get_config_path", lambda: cfg)
    monkeypatch.setattr(
        "configure_webhook._config.find_hermes_exe", lambda: "C:/fake/hermes.exe"
    )
    return cfg


def test_main_restart_root_refusal_returns_zero(monkeypatch, tmp_path, capsys) -> None:
    """集成：config 写入成功 + 重启被 root 拒绝 → main 返回 0（配置成功不应判失败）。"""
    _config_chain(monkeypatch, tmp_path)
    _monkey_restart(
        monkeypatch,
        _FakeCompleted(
            returncode=1,
            stderr="Refusing to install the gateway system service as root; "
            "pass --run-as-user root to override (e.g. in LXC containers)\n",
        ),
    )
    rc = configure_webhook.main(["--secret", "s3cr3t"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "WARN" in out and "下次重启" in out


def test_main_restart_unrelated_failure_returns_one(monkeypatch, tmp_path) -> None:
    """集成：重启遇到无关失败 → main 返回 1。"""
    _config_chain(monkeypatch, tmp_path)
    _monkey_restart(
        monkeypatch,
        _FakeCompleted(returncode=1, stderr="systemctl: command not found\n"),
    )
    rc = configure_webhook.main(["--secret", "s3cr3t"])
    assert rc == 1


def test_main_no_restart_skips_run(monkeypatch, tmp_path, capsys) -> None:
    """集成：--no-restart 时不调用 run_command，返回 0 并打印手动命令。"""
    _config_chain(monkeypatch, tmp_path)
    calls = []

    def fake_run(cmd, timeout=120):
        calls.append(cmd)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr("configure_webhook._config.run_command", fake_run)
    rc = configure_webhook.main(["--secret", "s3cr3t", "--no-restart"])
    assert rc == 0
    assert not calls  # --no-restart 分支不执行任何子进程
    assert "gateway restart" in capsys.readouterr().out  # 打印手动重启命令


def test_main_restart_success_returns_zero(monkeypatch, tmp_path) -> None:
    """集成：重启成功 → main 返回 0。"""
    _config_chain(monkeypatch, tmp_path)
    _monkey_restart(monkeypatch, _FakeCompleted(returncode=0))
    rc = configure_webhook.main(["--secret", "s3cr3t"])
    assert rc == 0
