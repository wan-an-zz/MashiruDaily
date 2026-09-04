"""bootstrap.py 一键初始化程序的离线契约测试（全部 mock，不执行真实进程）。

所有用例通过 monkeypatch 覆盖 bootstrap 模块级引用（subprocess.run / Popen /
urllib.request.urlopen / os.name / time.sleep / os.environ 等），绝不触发真实
子进程、网络请求或文件写入。
"""

import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

import bootstrap  # noqa: E402 — bootstrap.py 尚不存在时为预期的 RED collection error


# ---------------------------------------------------------------------------
# 辅助构造与公共 fake
# ---------------------------------------------------------------------------


class _FakeCompleted:
    """模拟 subprocess.run 的返回对象。"""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class _FakeProc:
    """模拟 subprocess.Popen 返回的进程对象（verify 步骤用，POSIX 清理分支）。"""

    def __init__(self, exit_code=None, stderr_lines=("",)):
        self._exit_code = exit_code
        self.stderr_lines = list(stderr_lines)
        self.terminate_called = False
        self.kill_called = False
        self.wait_called = False

    def poll(self):
        """服务器进程状态：None=运行中，非 None=已退出（返回其退出码）。"""
        return self._exit_code

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True

    def wait(self, timeout=None):
        self.wait_called = True
        return self._exit_code


class _FakeHttpResponse:
    """模拟 urllib.request.urlopen 的响应对象。"""

    def __init__(self, body: bytes = b"{}", status: int = 200):
        self._body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body

    def getcode(self):
        return self.status


def _monkey_run(monkeypatch, script: str, returncode: int = 0, stdout: str = ""):
    """替换 bootstrap.subprocess.run 为记录型 fake，按脚本名（子串匹配）返回预设结果。"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        if any(script in str(c) for c in cmd):
            return _FakeCompleted(returncode=returncode, stdout=stdout)
        return _FakeCompleted(returncode=0, stdout="")

    monkeypatch.setattr("bootstrap.subprocess.run", fake_run)
    return calls


def _monkey_popen(monkeypatch, proc):
    """将 bootstrap.subprocess.Popen 替换为返回预设进程对象。"""
    monkeypatch.setattr("bootstrap.subprocess.Popen", lambda *a, **k: proc)


def _monkey_urlopen(monkeypatch, responses: dict):
    """将 bootstrap.urllib.request.urlopen 替换为按 URL 返回预设响应。"""

    def fake_urlopen(url, timeout=5):
        if url not in responses:
            raise urllib.error.HTTPError(url, 404, "not found", None, None)
        return responses[url]

    monkeypatch.setattr("bootstrap.urllib.request.urlopen", fake_urlopen)


def _valid_meta_body() -> bytes:
    """构造合法的 /api/todo/meta 响应体（含 created_at）。"""
    return json.dumps(
        {"date": "2026-08-14", "created_at": "2026-08-14T09:00:00+08:00", "count": 0}
    ).encode("utf-8")


@pytest.fixture(autouse=True)
def _no_real_io(monkeypatch):
    """全局兜底：任何未显式 mock 的 subprocess.run 都被拦截并视为测试错误；
    轮询 sleep 替换为空操作，避免测试真实等待。"""
    def fake_run(cmd, **kwargs):
        raise AssertionError(f"测试不应执行真实子进程：{cmd}")

    monkeypatch.setattr("bootstrap.subprocess.run", fake_run)
    monkeypatch.setattr("bootstrap.time.sleep", lambda s: None)


# ---------------------------------------------------------------------------
# venv python 路径选择
# ---------------------------------------------------------------------------


def test_venv_python_nt_uses_scripts(monkeypatch) -> None:
    """Windows 下 venv python 路径应为 <venv>/Scripts/python.exe。"""
    monkeypatch.setattr("bootstrap.os.name", "nt")
    assert bootstrap.venv_python(Path("C:/fake/server/.venv")) == Path(
        "C:/fake/server/.venv/Scripts/python.exe"
    )


def test_venv_python_posix_uses_bin(monkeypatch) -> None:
    """POSIX 下 venv python 路径应为 <venv>/bin/python。"""
    monkeypatch.setattr("bootstrap.os.name", "posix")
    assert bootstrap.venv_python(Path("/fake/server/.venv")) == Path(
        "/fake/server/.venv/bin/python"
    )


# ---------------------------------------------------------------------------
# setup_server 步骤
# ---------------------------------------------------------------------------


def test_setup_called_with_system_python_and_default_venv(monkeypatch) -> None:
    """默认调用：setup_server 使用系统 python 且透传 --venv .venv。"""
    calls = _monkey_run(monkeypatch, "setup_server.py")
    rc = bootstrap.main(["--skip-skills", "--skip-webhook", "--skip-cron",
                         "--skip-autostart", "--no-verify"])
    assert rc == 0
    setup_cmd = next(c for c, _ in calls if "setup_server.py" in c)
    assert setup_cmd[0] == sys.executable
    assert setup_cmd[1].endswith("setup_server.py")
    assert "--venv" in setup_cmd and setup_cmd[setup_cmd.index("--venv") + 1] == ".venv"


def test_custom_venv_flows_to_setup(monkeypatch) -> None:
    """自定义 --venv myenv 应透传到 setup_server。"""
    calls = _monkey_run(monkeypatch, "setup_server.py")
    bootstrap.main(["--venv", "myenv", "--skip-skills", "--skip-webhook",
                    "--skip-cron", "--skip-autostart", "--no-verify"])
    setup_cmd = next(c for c, _ in calls if "setup_server.py" in c)
    assert setup_cmd[setup_cmd.index("--venv") + 1] == "myenv"


def test_skip_setup_suppresses_setup(monkeypatch) -> None:
    """--skip-setup 时不应调用 setup_server。"""
    calls = _monkey_run(monkeypatch, "setup_server.py")
    bootstrap.main(["--skip-setup", "--skip-skills", "--skip-webhook",
                    "--skip-cron", "--skip-autostart", "--no-verify"])
    assert not any("setup_server.py" in c for c, _ in calls)


# ---------------------------------------------------------------------------
# 各 skip 标志
# ---------------------------------------------------------------------------


def test_each_skip_flag_suppresses_its_step(monkeypatch) -> None:
    """5 个 --skip-* 标志各自抑制对应步骤的调用。"""
    calls = _monkey_run(monkeypatch, "setup_server.py")
    bootstrap.main(["--skip-setup", "--skip-skills", "--skip-webhook",
                    "--skip-cron", "--skip-autostart", "--no-verify"])
    assert not any("setup_server.py" in c for c, _ in calls)
    assert not any("register_hermes_plugin.py" in c for c, _ in calls)
    assert not any("configure_webhook.py" in c for c, _ in calls)
    assert not any("configure_cron.py" in c for c, _ in calls)
    assert not any("install_autostart.py" in c for c, _ in calls)


def test_skip_setup_with_missing_venv_errors(monkeypatch) -> None:
    """--skip-setup 且 venv python 不存在（后续步骤仍需要）时应返回 1 并提示先跑 setup_server。"""
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    calls = _monkey_run(monkeypatch, "configure_cron.py")
    rc = bootstrap.main(["--skip-setup", "--skip-webhook", "--no-verify"])
    assert rc == 1
    assert not any("configure_cron.py" in c for c, _ in calls)


# ---------------------------------------------------------------------------
# secret 处理
# ---------------------------------------------------------------------------


def test_missing_secret_fails_fast(monkeypatch) -> None:
    """缺 secret（无 --secret 且无环境变量）且 webhook 启用时应返回 1，configure_webhook 不被调用。"""
    monkeypatch.setattr("bootstrap.os.environ", {})
    calls = _monkey_run(monkeypatch, "configure_webhook.py")
    rc = bootstrap.main(["--skip-autostart", "--no-verify"])
    assert rc == 1
    assert not any("configure_webhook.py" in c for c, _ in calls)


def test_secret_injected_via_env_not_cmdline(monkeypatch) -> None:
    """secret 应通过子进程环境变量注入，绝不出现于命令行参数。"""
    calls = _monkey_run(monkeypatch, "configure_webhook.py")
    rc = bootstrap.main(["--secret", "s3cr3t", "--skip-autostart", "--no-verify"])
    assert rc == 0
    webhook_call = next((c, k) for c, k in calls if "configure_webhook.py" in c)
    assert "s3cr3t" not in webhook_call[0]
    env = webhook_call[1].get("env", {})
    assert env.get("MASHIRU_WEBHOOK_SECRET") == "s3cr3t"


def test_inherited_env_secret_accepted(monkeypatch) -> None:
    """继承环境变量 MASHIRU_WEBHOOK_SECRET 时无需 --secret 即可通过。"""
    monkeypatch.setattr("bootstrap.os.environ",
                        {"MASHIRU_WEBHOOK_SECRET": "env-secret"})
    calls = _monkey_run(monkeypatch, "configure_webhook.py")
    rc = bootstrap.main(["--skip-autostart", "--no-verify"])
    assert rc == 0
    webhook_call = next((c, k) for c, k in calls if "configure_webhook.py" in c)
    assert webhook_call[1]["env"]["MASHIRU_WEBHOOK_SECRET"] == "env-secret"


# ---------------------------------------------------------------------------
# 参数透传
# ---------------------------------------------------------------------------


def test_no_restart_passthrough(monkeypatch) -> None:
    """--no-restart 应透传给 configure_webhook。"""
    monkeypatch.setattr("bootstrap.os.environ",
                        {"MASHIRU_WEBHOOK_SECRET": "env-secret"})
    calls = _monkey_run(monkeypatch, "configure_webhook.py")
    bootstrap.main(["--no-restart", "--skip-autostart", "--no-verify"])
    webhook_cmd = next(c for c, _ in calls if "configure_webhook.py" in c)
    assert "--no-restart" in webhook_cmd


def test_schedule_passthrough(monkeypatch) -> None:
    """--schedule 应透传给 configure_cron。"""
    monkeypatch.setattr("bootstrap.os.environ",
                        {"MASHIRU_WEBHOOK_SECRET": "env-secret"})
    calls = _monkey_run(monkeypatch, "configure_cron.py")
    bootstrap.main(["--schedule", "0 8 * * *", "--skip-autostart", "--no-verify"])
    cron_cmd = next(c for c, _ in calls if "configure_cron.py" in c)
    assert "0 8 * * *" in cron_cmd


# ---------------------------------------------------------------------------
# fail-fast 与退出码
# ---------------------------------------------------------------------------


def test_fail_fast_stops_on_first_failure(monkeypatch) -> None:
    """configure_webhook 返回 7 时应立即终止，后续 cron/autostart 不被调用，main 返回 7。"""
    monkeypatch.setattr("bootstrap.os.environ",
                        {"MASHIRU_WEBHOOK_SECRET": "env-secret"})
    calls = _monkey_run(monkeypatch, "configure_webhook.py", returncode=7)
    rc = bootstrap.main(["--skip-autostart", "--no-verify"])
    assert rc == 7
    assert not any("configure_cron.py" in c for c, _ in calls)
    assert not any("install_autostart.py" in c for c, _ in calls)


def test_exit_code_propagated(monkeypatch) -> None:
    """webhook 步骤返回未知非零退出码（非 1/2/3）时 main 应透传该退出码。"""
    monkeypatch.setattr("bootstrap.os.environ",
                        {"MASHIRU_WEBHOOK_SECRET": "env-secret"})
    _monkey_run(monkeypatch, "configure_webhook.py", returncode=4)
    rc = bootstrap.main(["--skip-autostart", "--no-verify"])
    assert rc == 4


def test_webhook_root_refusal_is_nonfatal_and_prompted(monkeypatch, capsys) -> None:
    """webhook 步骤返回 2（root 拒绝重启）应视为成功，并在末尾重放提示。"""
    monkeypatch.setattr("bootstrap.os.environ",
                        {"MASHIRU_WEBHOOK_SECRET": "env-secret"})
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    calls = _monkey_run(monkeypatch, "configure_webhook.py", returncode=2)
    rc = bootstrap.main(["--skip-autostart", "--no-verify"])
    assert rc == 0
    assert any("configure_cron.py" in c for c, _ in calls)
    out = capsys.readouterr().out
    assert "以下操作需要您手动完成，请勿遗漏：" in out
    assert "Hermes 拒绝在 root 下重启网关" in out


def test_webhook_user_systemd_is_nonfatal_and_prompted(monkeypatch, capsys) -> None:
    """webhook 步骤返回 3（用户级 systemd 不可达）应视为成功，并在末尾重放提示。"""
    monkeypatch.setattr("bootstrap.os.environ",
                        {"MASHIRU_WEBHOOK_SECRET": "env-secret"})
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    calls = _monkey_run(monkeypatch, "configure_webhook.py", returncode=3)
    rc = bootstrap.main(["--skip-autostart", "--no-verify"])
    assert rc == 0
    assert any("configure_cron.py" in c for c, _ in calls)
    out = capsys.readouterr().out
    assert "以下操作需要您手动完成，请勿遗漏：" in out
    assert "Hermes所属用户" in out


def test_autostart_manual_exit_is_nonfatal_and_prompted(monkeypatch, capsys) -> None:
    """install_autostart 返回 2（Windows 非管理员、需手动完成）→ 不判失败、继续流程，末尾重放手动提示。"""
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    calls = _monkey_run(monkeypatch, "install_autostart.py", returncode=2)
    rc = bootstrap.main(["--skip-setup", "--skip-skills", "--skip-webhook",
                         "--skip-cron", "--no-verify"])
    assert rc == 0
    assert any("install_autostart.py" in c for c, _ in calls)
    out = capsys.readouterr().out
    assert "以下操作需要您手动完成，请勿遗漏：" in out
    assert "开机自启" in out
    assert "管理员" in out
    assert "install_autostart.py" in out
    assert "[FAIL] install_autostart.py 失败" not in out


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def test_dry_run_only_executes_autostart_with_flag(monkeypatch) -> None:
    """dry-run：仅 install_autostart 以 --dry-run 真实执行（只读演练），其余步骤打印跳过，返回 0。"""
    calls = _monkey_run(monkeypatch, "install_autostart.py")
    rc = bootstrap.main(["--dry-run", "--secret", "demo", "--no-verify"])
    assert rc == 0
    autostart_calls = [c for c, _ in calls if "install_autostart.py" in c]
    assert len(autostart_calls) == 1
    assert "--dry-run" in autostart_calls[0]
    assert not any("setup_server.py" in c for c, _ in calls)
    assert not any("register_hermes_plugin.py" in c for c, _ in calls)
    assert not any("configure_webhook.py" in c for c, _ in calls)
    assert not any("configure_cron.py" in c for c, _ in calls)


def test_dry_run_with_missing_secret_still_fails(monkeypatch) -> None:
    """dry-run 下缺 secret 仍应返回 1（忠实预演真实运行）。"""
    monkeypatch.setattr("bootstrap.os.environ", {})
    rc = bootstrap.main(["--dry-run", "--skip-autostart", "--no-verify"])
    assert rc == 1


def test_dry_run_skips_verify_without_no_verify(monkeypatch) -> None:
    """dry-run 且未 --no-verify 时 verify 步骤也应演练跳过，不真实探测端口。"""
    urlopen_called = []

    def fake_urlopen(url, timeout=5):
        urlopen_called.append(url)
        raise urllib.error.URLError("dry-run 不应真实探测")

    monkeypatch.setattr("bootstrap.urllib.request.urlopen", fake_urlopen)
    popen_called = []

    def fake_popen(*a, **k):
        popen_called.append(a)
        return _FakeProc(exit_code=None)

    monkeypatch.setattr("bootstrap.subprocess.Popen", fake_popen)
    rc = bootstrap.main(["--dry-run", "--secret", "demo", "--skip-autostart"])
    assert rc == 0
    assert not urlopen_called
    assert not popen_called


# ---------------------------------------------------------------------------
# verify 步骤（统一走 POSIX 清理分支，避免真实 taskkill）
# ---------------------------------------------------------------------------


def _verify_args() -> list:
    """全 skip + 保留 verify 的公共参数。"""
    return ["--skip-setup", "--skip-skills", "--skip-webhook",
            "--skip-cron", "--skip-autostart"]


def test_verify_health_then_meta_and_terminates(monkeypatch) -> None:
    """验证通过：health 200 + meta 合法 → 返回 0，子进程被终止。"""
    monkeypatch.setattr("bootstrap.os.name", "posix")
    responses = {
        "http://127.0.0.1:8123/health": _FakeHttpResponse(b'{"status":"ok"}'),
        "http://127.0.0.1:8123/api/todo/meta": _FakeHttpResponse(_valid_meta_body()),
    }
    _monkey_urlopen(monkeypatch, responses)
    proc = _FakeProc(exit_code=None)
    _monkey_popen(monkeypatch, proc)
    rc = bootstrap.main(_verify_args())
    assert rc == 0
    assert proc.terminate_called or proc.kill_called


def test_verify_health_never_200_returns_one(monkeypatch) -> None:
    """health 永不 200（轮询超时）→ 返回 1 且子进程被清理。"""
    monkeypatch.setattr("bootstrap.os.name", "posix")

    def fake_urlopen(url, timeout=5):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("bootstrap.urllib.request.urlopen", fake_urlopen)
    proc = _FakeProc(exit_code=None)
    _monkey_popen(monkeypatch, proc)
    rc = bootstrap.main(_verify_args())
    assert rc == 1
    assert proc.terminate_called or proc.kill_called


def test_verify_crashed_server_fails_quickly(monkeypatch) -> None:
    """服务器进程崩溃（poll 非 None）→ 快速返回 1，不等待完整超时。"""
    monkeypatch.setattr("bootstrap.os.name", "posix")

    def fake_urlopen(url, timeout=5):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr("bootstrap.urllib.request.urlopen", fake_urlopen)
    proc = _FakeProc(exit_code=1, stderr_lines=("Fatal error",))
    _monkey_popen(monkeypatch, proc)
    rc = bootstrap.main(_verify_args())
    assert rc == 1


def test_verify_reuses_existing_server(monkeypatch) -> None:
    """Windows 下 health 在 spawn 前已 200（服务器已在运行）→ 不调用 Popen，检查 meta 后返回 0。

    实现语义：仅 Windows 分支复用现有实例（POSIX 恒拉起独立实例验证），
    故此处固定 os.name="nt" 使测试与实现分支一致、平台无关。
    """
    monkeypatch.setattr("bootstrap.os.name", "nt")
    responses = {
        "http://127.0.0.1:8123/health": _FakeHttpResponse(b'{"status":"ok"}'),
        "http://127.0.0.1:8123/api/todo/meta": _FakeHttpResponse(_valid_meta_body()),
    }
    _monkey_urlopen(monkeypatch, responses)
    popen_called = []

    def fake_popen(*a, **k):
        popen_called.append(a)
        return _FakeProc(exit_code=None)

    monkeypatch.setattr("bootstrap.subprocess.Popen", fake_popen)
    rc = bootstrap.main(_verify_args())
    assert rc == 0
    assert not popen_called


def test_verify_bad_meta_returns_one(monkeypatch) -> None:
    """meta 200 但缺少 created_at → 返回 1。"""
    monkeypatch.setattr("bootstrap.os.name", "posix")
    responses = {
        "http://127.0.0.1:8123/health": _FakeHttpResponse(b'{"status":"ok"}'),
        "http://127.0.0.1:8123/api/todo/meta": _FakeHttpResponse(b'{"date":"2026-08-14"}'),
    }
    _monkey_urlopen(monkeypatch, responses)
    proc = _FakeProc(exit_code=None)
    _monkey_popen(monkeypatch, proc)
    rc = bootstrap.main(_verify_args())
    assert rc == 1


def test_verify_no_verify_skips_popen(monkeypatch) -> None:
    """--no-verify 时不应调用 Popen。"""
    popen_called = []

    def fake_popen(*a, **k):
        popen_called.append(a)
        return _FakeProc(exit_code=None)

    monkeypatch.setattr("bootstrap.subprocess.Popen", fake_popen)
    rc = bootstrap.main(["--skip-setup", "--skip-skills", "--skip-webhook",
                         "--skip-cron", "--skip-autostart", "--no-verify"])
    assert rc == 0
    assert not popen_called


def test_missing_secret_prompt_replayed_at_end(monkeypatch, capsys) -> None:
    """缺 secret 失败时，末尾应再次输出要求用户提供密钥的提示。"""
    monkeypatch.setattr("bootstrap.os.environ", {})
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    _monkey_run(monkeypatch, "configure_webhook.py")
    rc = bootstrap.main(["--skip-autostart", "--no-verify"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "以下操作需要您手动完成，请勿遗漏：" in out
    assert "请通过 --secret <密钥> 或环境变量 MASHIRU_WEBHOOK_SECRET 提供" in out


def test_missing_venv_prompt_replayed_at_end(monkeypatch, capsys) -> None:
    """--skip-setup 且 venv 缺失时，末尾应再次输出先运行 setup_server 的提示。"""
    monkeypatch.setattr(Path, "is_file", lambda self: False)
    _monkey_run(monkeypatch, "configure_cron.py")
    rc = bootstrap.main(["--skip-setup", "--skip-webhook", "--no-verify"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "以下操作需要您手动完成，请勿遗漏：" in out
    assert "请先运行 setup_server.py 创建虚拟环境" in out


def test_custom_venv_warning_replayed_at_end(monkeypatch, capsys) -> None:
    """自定义 --venv 时，末尾应再次输出 install_autostart 硬编码 .venv 的警告。"""
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    _monkey_run(monkeypatch, "install_autostart.py")
    rc = bootstrap.main(["--venv", "myenv", "--skip-setup", "--skip-skills",
                         "--skip-webhook", "--skip-cron", "--no-verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "以下操作需要您手动完成，请勿遗漏：" in out
    assert "install_autostart 硬编码 .venv，自定义虚拟环境名不会生效" in out


def test_no_restart_manual_restart_replayed_at_end(monkeypatch, capsys) -> None:
    """--no-restart 成功配置后，末尾应再次输出手动重启网关的提示。"""
    monkeypatch.setattr("bootstrap.os.environ",
                        {"MASHIRU_WEBHOOK_SECRET": "env-secret"})
    monkeypatch.setattr(Path, "is_file", lambda self: True)
    _monkey_run(monkeypatch, "configure_webhook.py")
    rc = bootstrap.main(["--no-restart", "--skip-autostart", "--no-verify"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "以下操作需要您手动完成，请勿遗漏：" in out
    assert "hermes gateway restart" in out


def test_no_action_prompt_summary_when_none_recorded(monkeypatch, capsys) -> None:
    """全程无用户操作提示时，末尾不应输出汇总块。"""
    _monkey_run(monkeypatch, "setup_server.py")
    rc = bootstrap.main(["--skip-setup", "--skip-skills", "--skip-webhook",
                         "--skip-cron", "--skip-autostart", "--no-verify"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "以下操作需要您手动完成，请勿遗漏：" not in captured.err
    assert "以下操作需要您手动完成，请勿遗漏：" not in captured.out
