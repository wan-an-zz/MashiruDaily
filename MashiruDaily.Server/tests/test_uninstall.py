"""uninstall.py 一键卸载程序的离线契约测试（全部 mock，不执行真实进程）。

所有用例通过 monkeypatch 覆盖模块级引用（subprocess.run / shutil.rmtree /
os.name / os.environ / _config.* / configure_webhook._restart_gateway 等），
绝不触发真实子进程、网络请求或目录删除（junction 用例除外——创建真实 junction
不需要管理员权限，且删除路径经 _config.run_command mock，仅创建步骤用真实
cmd 命令）。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
import ruamel.yaml

import uninstall  # noqa: E402 — uninstall.py 尚不存在时为预期的 RED collection error


# ---------------------------------------------------------------------------
# 辅助构造与公共 fake
# ---------------------------------------------------------------------------


class _FakeCompleted:
    """模拟 subprocess 返回对象（CompletedProcess 形状）。"""

    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture(autouse=True)
def calls(monkeypatch, tmp_path):
    """全局兜底（夹具名 calls，测试经参数引用其记录）：SERVER_ROOT 指向临时目录、
    数据目录与 HERMES_HOME 指向临时目录、拦截真实子进程与目录删除（记录 rmtree 调用）。

    任何未显式 mock 的 subprocess.run 都被拦截并视为测试错误；
    shutil.rmtree 被替换为记录型 fake，防止误删真实路径。
    """
    records: dict = {"rmtree": [], "orig_run": subprocess.run}
    monkeypatch.setattr("uninstall.SERVER_ROOT", tmp_path / "server")
    monkeypatch.setenv("MASHIRU_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "hermes"))

    def fake_run(cmd, **kwargs):
        raise AssertionError(f"测试不应执行真实子进程：{cmd}")

    monkeypatch.setattr("uninstall.subprocess.run", fake_run)

    def fake_rmtree(path, *args, **kwargs):
        records["rmtree"].append(Path(path))

    monkeypatch.setattr("uninstall.shutil.rmtree", fake_rmtree)
    return records


def _monkey_run(monkeypatch, returncode: int = 0, stdout: str = "", stderr: str = ""):
    """替换 uninstall.subprocess.run 为记录型 fake，返回记录列表。"""
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((list(cmd), kwargs))
        return _FakeCompleted(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("uninstall.subprocess.run", fake_run)
    return calls


def _monkey_run_command(
    monkeypatch, returncode: int = 0, stdout: str = "", stderr: str = ""
):
    """替换 uninstall._config.run_command 为记录型 fake，返回记录列表。"""
    calls = []

    def fake_run(cmd, timeout=120):
        calls.append(list(cmd))
        return _FakeCompleted(returncode=returncode, stdout=stdout, stderr=stderr)

    monkeypatch.setattr("uninstall._config.run_command", fake_run)
    return calls


def _make_config(tmp_path: Path, text: str) -> Path:
    """在临时 HERMES_HOME 下写入 config.yaml 并让 uninstall 指向它。"""
    cfg = tmp_path / "hermes" / "config.yaml"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(text, encoding="utf-8")
    return cfg


def _point_config(monkeypatch, cfg: Path) -> None:
    monkeypatch.setattr("uninstall._config.get_config_path", lambda: cfg)


def _read_yaml(path: Path):
    """以 round-trip 模式读取 YAML（与 _config.load_config 同源）。"""
    yaml_obj = uninstall._config.new_yaml()
    with open(path, "r", encoding="utf-8") as f:
        return yaml_obj.load(f)


def _skills_paths(tmp_path: Path) -> tuple:
    """返回 uninstall 期望从 config.yaml 中清除的两条 skills 路径。"""
    new_dir = (tmp_path / "server" / "hermes_plugin" / "mashiru_daily" / "skills").as_posix()
    legacy_dir = (tmp_path / "server" / "skills").as_posix()
    return new_dir, legacy_dir


# ---------------------------------------------------------------------------
# venv python 路径选择
# ---------------------------------------------------------------------------


def test_venv_python_nt_uses_scripts(monkeypatch) -> None:
    """Windows 下 venv python 路径应为 <venv>/Scripts/python.exe。"""
    monkeypatch.setattr("uninstall.os.name", "nt")
    assert uninstall.venv_python(Path("C:/fake/server/.venv")) == Path(
        "C:/fake/server/.venv/Scripts/python.exe"
    )


def test_venv_python_posix_uses_bin(monkeypatch) -> None:
    """POSIX 下 venv python 路径应为 <venv>/bin/python。"""
    monkeypatch.setattr("uninstall.os.name", "posix")
    assert uninstall.venv_python(Path("/fake/server/.venv")) == Path(
        "/fake/server/.venv/bin/python"
    )


# ---------------------------------------------------------------------------
# 步骤 1：停止运行中的服务器进程
# ---------------------------------------------------------------------------


def test_stop_server_windows_uses_powershell_cim(monkeypatch) -> None:
    """Windows：停止命令应走 PowerShell CIM，过滤含 app.main 的命令行并排除自身 PID。"""
    monkeypatch.setattr("uninstall.os.name", "nt")
    calls = _monkey_run(monkeypatch)
    assert uninstall._stop_server(dry_run=False, no_stop=False)
    assert len(calls) == 1
    cmd = calls[0][0]
    assert cmd[0].lower().endswith("powershell")
    joined = " ".join(cmd)
    assert "Get-CimInstance Win32_Process" in joined
    assert "*app.main*" in joined
    assert "-ne $PID" in joined


def test_stop_server_posix_uses_pkill(monkeypatch) -> None:
    """POSIX：停止命令应为 pkill -f app.main。"""
    monkeypatch.setattr("uninstall.os.name", "posix")
    calls = _monkey_run(monkeypatch)
    assert uninstall._stop_server(dry_run=False, no_stop=False)
    assert calls[0][0] == ["pkill", "-f", "app.main"]


def test_stop_server_pkill_no_match_is_ok(monkeypatch) -> None:
    """POSIX：pkill 返回 1（无匹配进程）应视为正常（没有进程可杀），不判失败。"""
    monkeypatch.setattr("uninstall.os.name", "posix")
    _monkey_run(monkeypatch, returncode=1)
    assert uninstall._stop_server(dry_run=False, no_stop=False)


def test_stop_server_no_stop_skips(monkeypatch) -> None:
    """--no-stop 时不应调用任何子进程。"""
    calls = _monkey_run(monkeypatch)
    assert uninstall._stop_server(dry_run=False, no_stop=True)
    assert not calls


# ---------------------------------------------------------------------------
# 步骤 2：移除开机自启
# ---------------------------------------------------------------------------


def test_autostart_uninstall_called_with_system_python(monkeypatch) -> None:
    """默认调用：以系统 python 运行 install_autostart.py --uninstall。"""
    calls = _monkey_run(monkeypatch)
    assert uninstall._remove_autostart(dry_run=False, skip=False)
    autostart_cmd = next(c for c, _ in calls if "install_autostart.py" in c)
    assert autostart_cmd[0] == sys.executable
    assert "--uninstall" in autostart_cmd


def test_autostart_dry_run_passes_flag(monkeypatch) -> None:
    """dry-run：install_autostart 以 --dry-run 真实执行（只读演练）。"""
    calls = _monkey_run(monkeypatch)
    assert uninstall._remove_autostart(dry_run=True, skip=False)
    autostart_cmd = next(c for c, _ in calls if "install_autostart.py" in c)
    assert "--dry-run" in autostart_cmd


def test_autostart_skip_suppresses_call(monkeypatch) -> None:
    """--skip-autostart 时不应调用 install_autostart。"""
    calls = _monkey_run(monkeypatch)
    assert uninstall._remove_autostart(dry_run=False, skip=True)
    assert not any("install_autostart.py" in c for c, _ in calls)


def test_autostart_failure_recorded(monkeypatch) -> None:
    """install_autostart 返回非零 → 步骤失败（返回 False）。"""
    _monkey_run(monkeypatch, returncode=5)
    assert not uninstall._remove_autostart(dry_run=False, skip=False)


def test_autostart_manual_exit_2_is_not_failure(monkeypatch) -> None:
    """install_autostart 返回 2（Windows 非管理员、需手动完成）→ 步骤不算失败，并记录手动提示。"""
    uninstall._ACTION_PROMPTS.clear()
    try:
        _monkey_run(monkeypatch, returncode=2)
        assert uninstall._remove_autostart(dry_run=False, skip=False)
        assert any("开机自启" in p and "管理员" in p for p in uninstall._ACTION_PROMPTS)
    finally:
        uninstall._ACTION_PROMPTS.clear()


# ---------------------------------------------------------------------------
# 步骤 3：删除每日 cron 任务
# ---------------------------------------------------------------------------


CRON_LIST_WITH_JOB = (
    "┌──────────────────────────────────┐\n"
    "│           Scheduled Jobs          │\n"
    "└──────────────────────────────────┘\n"
    "\n"
    "  a1b2c3d4 [active]\n"
    "    Name:      mashiru-daily\n"
    "    Schedule:  0 9 * * *\n"
)


def test_cron_remove_when_job_found(monkeypatch) -> None:
    """cron list 中出现 mashiru-daily 任务 → 调用 hermes cron remove（位置参数=任务名）。"""
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    calls = _monkey_run_command(monkeypatch, stdout=CRON_LIST_WITH_JOB)
    assert uninstall._remove_cron(dry_run=False, skip=False)
    list_calls = [c for c in calls if "cron" in c and "list" in c]
    remove_calls = [c for c in calls if "cron" in c and "remove" in c]
    assert len(list_calls) == 1
    assert list_calls[0] == ["C:/fake/hermes.exe", "cron", "list", "--all"]
    assert len(remove_calls) == 1
    assert remove_calls[0] == ["C:/fake/hermes.exe", "cron", "remove", "mashiru-daily"]


def test_cron_remove_skipped_when_absent(monkeypatch) -> None:
    """cron list 中无该任务 → 不调用 remove。"""
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    calls = _monkey_run_command(monkeypatch, stdout="No scheduled jobs.\n")
    assert uninstall._remove_cron(dry_run=False, skip=False)
    assert not any("remove" in c for c in calls)


def test_cron_remove_word_boundary(monkeypatch) -> None:
    """同名前缀任务（mashiru-daily-backup）不得被误判为 mashiru-daily。"""
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    calls = _monkey_run_command(
        monkeypatch,
        stdout="  abc12345 [active]\n    Name:      mashiru-daily-backup\n",
    )
    assert uninstall._remove_cron(dry_run=False, skip=False)
    assert not any("remove" in c for c in calls)


def test_cron_remove_command_failure_recorded(monkeypatch) -> None:
    """remove 命令返回非零（如任务不存在/同名歧义）→ 步骤失败。"""
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    _monkey_run_command(monkeypatch, stdout=CRON_LIST_WITH_JOB, returncode=1)
    assert not uninstall._remove_cron(dry_run=False, skip=False)


def test_cron_missing_hermes_warns_and_continues(monkeypatch, capsys) -> None:
    """找不到 hermes 可执行文件 → 提示手动删除并继续（不判失败）。"""
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    assert uninstall._remove_cron(dry_run=False, skip=False)
    out = capsys.readouterr().out
    assert "hermes" in out and "手动" in out


# ---------------------------------------------------------------------------
# 步骤 4：清理 webhook 配置
# ---------------------------------------------------------------------------


def test_webhook_removes_todo_sync_keeps_other_routes(monkeypatch, tmp_path) -> None:
    """config 含 todo-sync 与其他路由时 → 仅删除 todo-sync，其余路由保留。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  qqbot:\n"
        "    enabled: true\n"
        "  webhook:\n"
        "    enabled: true\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n"
        "        other-route:\n"
        "          events: [ping]\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=True, ruamel_ok=True
    )
    data = _read_yaml(cfg)
    routes = data["platforms"]["webhook"]["extra"]["routes"]
    assert "todo-sync" not in routes
    assert "other-route" in routes
    assert data["platforms"]["qqbot"]["enabled"] is True


def test_webhook_removes_whole_block_when_only_ours(monkeypatch, tmp_path) -> None:
    """config 只有本工具创建的 webhook 块（无全局 secret、无其他路由）→ 整块删除。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    enabled: true\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=True, ruamel_ok=True
    )
    data = _read_yaml(cfg)
    assert "webhook" not in data.get("platforms", {})
    # platforms 已空 → 一并清理
    assert "platforms" not in data


def test_webhook_keeps_block_when_global_secret(monkeypatch, tmp_path) -> None:
    """webhook 块存在全局 secret（非本工具所设）→ 保留块，仅移除 todo-sync 路由。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    enabled: true\n"
        "    extra:\n"
        "      port: 8644\n"
        "      secret: global-secret\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=True, ruamel_ok=True
    )
    data = _read_yaml(cfg)
    assert "webhook" in data["platforms"]
    assert "routes" not in data["platforms"]["webhook"]["extra"]
    assert data["platforms"]["webhook"]["extra"]["secret"] == "global-secret"


def test_webhook_absent_no_change_no_backup(monkeypatch, tmp_path) -> None:
    """config 无 webhook 配置 → 不修改、不产生备份文件。"""
    cfg = _make_config(tmp_path, "platforms:\n  qqbot:\n    enabled: true\n")
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=True, ruamel_ok=True
    )
    assert not list(tmp_path.glob("hermes/config.yaml.bak-*"))
    data = _read_yaml(cfg)
    assert data["platforms"]["qqbot"]["enabled"] is True


def test_webhook_backup_created_before_write(monkeypatch, tmp_path) -> None:
    """真正修改前应生成 config.yaml.bak-<时间戳> 备份。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=True, ruamel_ok=True
    )
    backups = list(tmp_path.glob("hermes/config.yaml.bak-*"))
    assert len(backups) == 1


class _FakeDatetime:
    """固定时间戳的 datetime 替身（同一秒内的多次备份文件名将冲突）。"""

    @staticmethod
    def now():
        return _FakeDatetime()

    def strftime(self, fmt: str) -> str:
        return "20260818120000"


def test_backup_config_unique_within_same_second(monkeypatch, tmp_path) -> None:
    """同一秒内连续两次备份（卸载 webhook 与插件两步同秒发生）→ 文件名不冲突，两份内容都保留。"""
    cfg = tmp_path / "hermes" / "config.yaml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("original: 1\n", encoding="utf-8")
    monkeypatch.setattr("uninstall._config.datetime", _FakeDatetime)
    first = uninstall._config.backup_config(cfg)
    cfg.write_text("original: 2\n", encoding="utf-8")
    second = uninstall._config.backup_config(cfg)
    assert first != second
    assert first.read_text(encoding="utf-8").strip() == "original: 1"
    assert second.read_text(encoding="utf-8").strip() == "original: 2"


def test_webhook_no_restart_prints_manual_command(monkeypatch, tmp_path, capsys) -> None:
    """--no-restart 时不执行网关重启，仅打印手动命令。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    run_calls = _monkey_run_command(monkeypatch)
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=True, ruamel_ok=True
    )
    assert not any("gateway" in c for c in run_calls)
    assert "gateway restart" in capsys.readouterr().out


def test_webhook_restart_success(monkeypatch, tmp_path) -> None:
    """webhook 变更后默认重启网关（复用 configure_webhook._restart_gateway）。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    restarted = []

    def fake_restart(hermes):
        restarted.append(hermes)
        return 0

    monkeypatch.setattr("uninstall.configure_webhook._restart_gateway", fake_restart)
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=False, ruamel_ok=True
    )
    assert restarted == ["C:/fake/hermes.exe"]


def test_webhook_restart_degraded_nonfatal(monkeypatch, tmp_path, capsys) -> None:
    """网关重启被 Hermes 良性拒绝（返回 2/3）→ 不判失败，提示下次重启生效。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    monkeypatch.setattr(
        "uninstall.configure_webhook._restart_gateway", lambda hermes: 2
    )
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=False, ruamel_ok=True
    )
    assert "下次重启" in capsys.readouterr().out


def test_webhook_restart_unrelated_failure_recorded(monkeypatch, tmp_path) -> None:
    """网关重启遇到无关失败（返回 1）→ 步骤判失败。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    monkeypatch.setattr(
        "uninstall.configure_webhook._restart_gateway", lambda hermes: 1
    )
    assert not uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=False, ruamel_ok=True
    )


def test_webhook_ruamel_unavailable_skipped(monkeypatch, tmp_path, capsys) -> None:
    """ruamel 不可用（无法读 config）→ 跳过配置清理并给出警告，不判失败。"""
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    assert uninstall._remove_webhook_config(
        dry_run=False, skip=False, no_restart=True, ruamel_ok=False
    )
    out = capsys.readouterr().out
    assert "ruamel" in out
    data = _read_yaml(cfg)  # config 未被改动
    assert "todo-sync" in data["platforms"]["webhook"]["extra"]["routes"]


# ---------------------------------------------------------------------------
# 步骤 5：移除 Hermes 插件注册
# ---------------------------------------------------------------------------


def test_plugin_config_entries_removed(monkeypatch, tmp_path) -> None:
    """plugins.enabled 与 skills.external_dirs 中的 mashiru 条目被清除，其余保留。"""
    new_dir, legacy_dir = _skills_paths(tmp_path)
    cfg = _make_config(
        tmp_path,
        "plugins:\n"
        "  enabled:\n"
        "    - mashiru-daily\n"
        "    - other-plugin\n"
        "skills:\n"
        "  external_dirs:\n"
        f"    - {new_dir}\n"
        f"    - {legacy_dir}\n"
        "    - /some/other/dir\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    assert uninstall._remove_plugin(dry_run=False, skip=False, ruamel_ok=True)
    data = _read_yaml(cfg)
    assert data["plugins"]["enabled"] == ["other-plugin"]
    assert data["skills"]["external_dirs"] == ["/some/other/dir"]


def test_plugin_config_cleans_empty_mappings(monkeypatch, tmp_path) -> None:
    """清除后为空 → 空列表键与空父键一并删除，保持配置整洁。"""
    new_dir, legacy_dir = _skills_paths(tmp_path)
    cfg = _make_config(
        tmp_path,
        "plugins:\n"
        "  enabled:\n"
        "    - mashiru-daily\n"
        "skills:\n"
        "  external_dirs:\n"
        f"    - {new_dir}\n"
        f"    - {legacy_dir}\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    assert uninstall._remove_plugin(dry_run=False, skip=False, ruamel_ok=True)
    data = _read_yaml(cfg)
    assert "plugins" not in data
    assert "skills" not in data


def test_plugin_cli_disable_called(monkeypatch, tmp_path) -> None:
    """找到 hermes → 调用 hermes plugins disable mashiru-daily。"""
    new_dir, legacy_dir = _skills_paths(tmp_path)
    cfg = _make_config(
        tmp_path,
        "plugins:\n"
        "  enabled:\n"
        "    - mashiru-daily\n"
        "skills:\n"
        "  external_dirs:\n"
        f"    - {new_dir}\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    calls = _monkey_run_command(monkeypatch)
    assert uninstall._remove_plugin(dry_run=False, skip=False, ruamel_ok=True)
    disable_calls = [c for c in calls if "plugins" in c and "disable" in c]
    assert len(disable_calls) == 1
    assert disable_calls[0] == ["C:/fake/hermes.exe", "plugins", "disable", "mashiru-daily"]


def test_plugin_cli_disable_failure_still_cleans_config(monkeypatch, tmp_path, capsys) -> None:
    """CLI disable 失败 → 警告但 config 清理仍继续执行。"""
    new_dir, legacy_dir = _skills_paths(tmp_path)
    cfg = _make_config(
        tmp_path,
        "plugins:\n"
        "  enabled:\n"
        "    - mashiru-daily\n"
        "skills:\n"
        "  external_dirs:\n"
        f"    - {new_dir}\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    _monkey_run_command(monkeypatch, returncode=1)
    assert uninstall._remove_plugin(dry_run=False, skip=False, ruamel_ok=True)
    data = _read_yaml(cfg)
    # 仅剩 mashiru-daily 一个条目 → 清空后 plugins 键整体删除（断言不产生 KeyError）
    assert "mashiru-daily" not in (data.get("plugins") or {}).get("enabled", [])


def test_plugin_link_kept_when_real_dir(monkeypatch, tmp_path, capsys) -> None:
    """插件目录是真实目录（非链接）→ 警告并保留，绝不删除。"""
    target = tmp_path / "hermes" / "plugins" / "mashiru-daily"
    target.mkdir(parents=True)
    (target / "plugin.yaml").write_text("name: mashiru-daily\n", encoding="utf-8")
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    assert uninstall._remove_plugin_link(dry_run=False)
    assert target.is_dir()
    err = capsys.readouterr().err
    assert "真实目录" in err


def test_plugin_link_kept_when_points_elsewhere(monkeypatch, tmp_path, calls, capsys) -> None:
    """链接指向其他位置（非本插件源）→ 警告并保留。"""
    other = tmp_path / "other-plugin-source"
    other.mkdir(parents=True)
    target = tmp_path / "hermes" / "plugins" / "mashiru-daily"
    target.parent.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        # 创建真实 junction（不需要管理员权限）
        monkeypatch.setattr("uninstall.subprocess.run", calls["orig_run"])
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(target), str(other)],
            check=True,
            capture_output=True,
        )
    else:
        target.symlink_to(other, target_is_directory=True)
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    assert uninstall._remove_plugin_link(dry_run=False)
    assert target.exists()
    err = capsys.readouterr().err
    assert "其他位置" in err


@pytest.mark.skipif(os.name != "nt", reason="Windows junction 语义")
def test_plugin_link_removed_when_junction_to_source(monkeypatch, tmp_path, calls) -> None:
    """Windows：指向本插件源的 junction → 用 cmd rmdir 删除接合点本身，目标目录保留。"""
    source = tmp_path / "server" / "hermes_plugin" / "mashiru_daily"
    source.mkdir(parents=True)
    (source / "plugin.yaml").write_text("name: mashiru-daily\n", encoding="utf-8")
    target = tmp_path / "hermes" / "plugins" / "mashiru-daily"
    target.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr("uninstall.subprocess.run", calls["orig_run"])
    subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(target), str(source)],
        check=True,
        capture_output=True,
    )
    assert target.is_junction()
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    # 记录 _config.run_command 调用，但对 rmdir 命令真实执行（验证端到端删除）
    recorded = []
    orig_run = calls["orig_run"]

    def fake_run_command(cmd, timeout=120):
        recorded.append(list(cmd))
        if len(cmd) >= 3 and cmd[0] == "cmd" and cmd[1] == "/c" and cmd[2] == "rmdir":
            orig_run(cmd, capture_output=True, text=True, errors="replace", timeout=30)
        return _FakeCompleted(returncode=0)

    monkeypatch.setattr("uninstall._config.run_command", fake_run_command)
    assert uninstall._remove_plugin_link(dry_run=False)
    assert not target.exists()
    assert source.is_dir()  # 目标目录未被递归删除
    rmdir_call = next(c for c in recorded if c[0] == "cmd" and c[1] == "/c")
    assert rmdir_call[2] == "rmdir" and rmdir_call[3] == str(target)


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink 语义")
def test_plugin_link_removed_when_symlink_to_source(monkeypatch, tmp_path) -> None:
    """POSIX：指向本插件源的 symlink → unlink 删除链接本身，目标目录保留。"""
    source = tmp_path / "server" / "hermes_plugin" / "mashiru_daily"
    source.mkdir(parents=True)
    target = tmp_path / "hermes" / "plugins" / "mashiru-daily"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.symlink_to(source, target_is_directory=True)
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    assert uninstall._remove_plugin_link(dry_run=False)
    assert not target.exists()
    assert source.is_dir()


def test_plugin_link_absent_skips(monkeypatch, tmp_path, capsys) -> None:
    """插件链接不存在 → SKIP，不判失败。"""
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    assert uninstall._remove_plugin_link(dry_run=False)
    assert "SKIP" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# 步骤 6/7：删除虚拟环境与数据目录
# ---------------------------------------------------------------------------


def test_venv_removed(monkeypatch, tmp_path, calls) -> None:
    """存在 .venv → rmtree 删除。"""
    venv_dir = tmp_path / "server" / ".venv"
    venv_dir.mkdir(parents=True)
    assert uninstall._remove_venv(
        dry_run=False, keep=False, venv_dir=venv_dir
    )
    assert venv_dir in calls["rmtree"]


def test_keep_venv_preserves(monkeypatch, tmp_path, calls) -> None:
    """--keep-venv → 不删除 .venv。"""
    venv_dir = tmp_path / "server" / ".venv"
    venv_dir.mkdir(parents=True)
    assert uninstall._remove_venv(dry_run=False, keep=True, venv_dir=venv_dir)
    assert not calls["rmtree"]
    assert venv_dir.is_dir()


def test_data_removed(monkeypatch, tmp_path, calls) -> None:
    """存在 data/ → rmtree 删除。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "todo.json").write_text("[]\n", encoding="utf-8")
    assert uninstall._remove_data(dry_run=False, keep=False, yes=True)
    assert data_dir in calls["rmtree"]


def test_keep_data_preserves(monkeypatch, tmp_path, calls) -> None:
    """--keep-data → 不删除 data/。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    assert uninstall._remove_data(dry_run=False, keep=True, yes=True)
    assert not calls["rmtree"]
    assert data_dir.is_dir()


def test_data_prompt_declined_aborts(monkeypatch, tmp_path, calls, capsys) -> None:
    """未 --yes 且用户拒绝确认 → 取消删除数据，不判失败。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    monkeypatch.setattr("uninstall.builtins.input", lambda *a: "n")
    assert uninstall._remove_data(dry_run=False, keep=False, yes=False)
    assert data_dir not in calls["rmtree"]
    assert data_dir.is_dir()
    assert "取消" in capsys.readouterr().out


def test_yes_skips_prompt(monkeypatch, tmp_path, calls) -> None:
    """--yes → 不弹确认，直接删除数据。"""
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)

    def boom(*a):
        raise AssertionError("--yes 不应触发确认提示")

    monkeypatch.setattr("uninstall.builtins.input", boom)
    assert uninstall._remove_data(dry_run=False, keep=False, yes=True)
    assert data_dir in calls["rmtree"]


def test_data_dir_respects_env(monkeypatch, tmp_path, calls) -> None:
    """MASHIRU_DATA_DIR 环境变量 → 删除该目录（而非默认 data/）。"""
    custom = tmp_path / "custom-data"
    custom.mkdir(parents=True)
    monkeypatch.setenv("MASHIRU_DATA_DIR", str(custom))
    assert uninstall._remove_data(dry_run=False, keep=False, yes=True)
    assert custom in calls["rmtree"]


def test_data_absent_skips(monkeypatch, tmp_path, calls, capsys) -> None:
    """data/ 不存在 → SKIP。"""
    assert uninstall._remove_data(dry_run=False, keep=False, yes=True)
    assert not calls["rmtree"]
    assert "SKIP" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# dry-run：零破坏性操作
# ---------------------------------------------------------------------------


def test_dry_run_no_destructive_ops(monkeypatch, tmp_path, calls) -> None:
    """dry-run：config 不落盘、venv/data 保留、不调用 list/remove/disable/rmdir。

    唯一真实执行的子进程是 install_autostart.py --dry-run（只读演练）。
    """
    monkeypatch.setattr("uninstall.os.name", "posix")
    new_dir, legacy_dir = _skills_paths(tmp_path)
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n"
        "plugins:\n"
        "  enabled:\n"
        "    - mashiru-daily\n"
        "skills:\n"
        "  external_dirs:\n"
        f"    - {new_dir}\n"
        f"    - {legacy_dir}\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    before = cfg.read_bytes()
    venv_dir = tmp_path / "server" / ".venv"
    venv_dir.mkdir(parents=True)
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True)
    run_calls = _monkey_run_command(monkeypatch)
    sub_calls = _monkey_run(monkeypatch)

    rc = uninstall.main(["--dry-run", "--yes"])
    assert rc == 0
    assert cfg.read_bytes() == before  # config 未落盘
    assert venv_dir.is_dir() and data_dir.is_dir()
    assert not calls["rmtree"]
    assert not run_calls  # 不调用任何 hermes CLI
    autostart_calls = [c for c, _ in sub_calls if "install_autostart.py" in c]
    assert len(autostart_calls) == 1
    assert "--dry-run" in autostart_calls[0]


def test_dry_run_prints_commands(monkeypatch, tmp_path, capsys) -> None:
    """dry-run：打印将执行的步骤（含 cron remove / 网关重启命令）。"""
    monkeypatch.setattr("uninstall.os.name", "posix")
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: "C:/fake/hermes.exe")
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    _monkey_run_command(monkeypatch, stdout=CRON_LIST_WITH_JOB)
    _monkey_run(monkeypatch)
    rc = uninstall.main(["--dry-run", "--yes"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "cron" in out and "remove" in out
    assert "gateway restart" in out


# ---------------------------------------------------------------------------
# ruamel 不可用时的整体降级
# ---------------------------------------------------------------------------


def test_ruamel_unavailable_skips_config_steps(monkeypatch, tmp_path, capsys) -> None:
    """系统与 venv 均无 ruamel → 跳过 webhook/插件 config 步骤并警告，其余步骤照常。"""
    monkeypatch.setattr("uninstall._ensure_ruamel", lambda venv_dir: False)
    monkeypatch.setattr("uninstall.os.name", "posix")
    # os.name 补丁影响 pathlib 实例化：mock config 路径隔离真实 pathlib 解析
    _point_config(monkeypatch, tmp_path / "hermes" / "config.yaml")
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    cfg = _make_config(
        tmp_path,
        "platforms:\n"
        "  webhook:\n"
        "    extra:\n"
        "      port: 8644\n"
        "      routes:\n"
        "        todo-sync:\n"
        "          events: [update]\n"
        "          secret: abc123\n",
    )
    _point_config(monkeypatch, cfg)
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    _monkey_run(monkeypatch)
    rc = uninstall.main(["--yes"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ruamel" in out
    data = _read_yaml(cfg)  # config 原样保留
    assert "todo-sync" in data["platforms"]["webhook"]["extra"]["routes"]


# ---------------------------------------------------------------------------
# main 集成
# ---------------------------------------------------------------------------


def test_main_nothing_installed_all_skip(monkeypatch, tmp_path, capsys) -> None:
    """完全未安装的环境：所有步骤 SKIP/继续，退出码 0，无破坏性操作。"""
    monkeypatch.setattr("uninstall.os.name", "posix")
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    # os.name 补丁影响 pathlib 实例化：mock config 路径隔离真实 pathlib 解析
    _point_config(monkeypatch, tmp_path / "hermes" / "config.yaml")
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    _monkey_run(monkeypatch)
    rc = uninstall.main(["--yes"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "SKIP" in out


def test_main_failure_aggregation(monkeypatch, tmp_path, capsys) -> None:
    """多步骤失败 → 聚合后返回 1，并在汇总中列出失败步骤。"""
    monkeypatch.setattr("uninstall.os.name", "posix")
    monkeypatch.setattr("uninstall._config.find_hermes_exe", lambda: None)
    _point_config(monkeypatch, tmp_path / "hermes" / "config.yaml")
    monkeypatch.setattr("uninstall._config.get_hermes_home", lambda: tmp_path / "hermes")
    _monkey_run(monkeypatch, returncode=5)  # stop 与 autostart 均失败
    rc = uninstall.main(["--yes"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "失败" in out
