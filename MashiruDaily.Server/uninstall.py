"""MashiruDaily.Server 一键卸载程序（uninstall.py，bootstrap.py 的逆操作）。

用系统 Python（纯标准库）按序执行七个卸载步骤，移除 MashiruDaily.Server 的
全部部署足迹（虚拟环境、数据目录、开机自启、cron 任务、webhook 配置、Hermes
插件注册），仅保留源码仓库本身：

    1. 停止运行中的服务器进程（按命令行 app.main 匹配，Windows 走 PowerShell
       CIM，POSIX 走 pkill）；
    2. 移除物理开机自启（复用 install_autostart.py --uninstall）；
    3. 删除每日 Hermes cron 任务（hermes cron list --all 幂等检查后 remove）；
    4. 清理 config.yaml 的 platforms.webhook todo-sync 路由（ruamel round-trip，
       修改前备份；随后重启 Hermes 网关使路由失效）；
    5. 移除 Hermes 插件注册（CLI disable + config.yaml 的 plugins.enabled /
       skills.external_dirs 条目 + plugins 目录链接，链接指向非本插件源时绝不删除）；
    6. 删除虚拟环境 .venv；
    7. 删除数据目录 data/（todo.json / todo-meta.json / plan.md / backups，
       删除前要求确认，--yes 跳过）。

与 bootstrap.py 的 fail-fast 不同：卸载步骤相互独立、尽力而为——单个步骤失败
会记录并在末尾汇总，其余步骤继续执行，最终返回非零退出码。config.yaml 的
config.yaml.bak-<时间戳> 备份文件（安装期生成）一律保留，它们可能是用户唯一
的配置副本。

config.yaml 相关步骤依赖 ruamel.yaml（round-trip 模式保留注释与格式）：优先
当前解释器，缺失时尝试注入虚拟环境的 site-packages（必须在删除虚拟环境之前
完成），仍不可用则跳过 config 步骤并给出手动清理指引。

用法（在 MashiruDaily.Server 目录下用系统 Python 运行）：
    python uninstall.py                       # 完整卸载（数据目录需确认）
    python uninstall.py --yes --keep-data     # 免确认 + 保留数据
    python uninstall.py --dry-run             # 演练：只打印将执行的命令
"""

import argparse
import builtins
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import _config  # 本目录共享的 Hermes 配置工具
import configure_webhook  # 复用其 _restart_gateway（含 root 拒绝降级逻辑）

# 服务器根目录（即本脚本所在目录）
SERVER_ROOT = Path(__file__).resolve().parent

# Hermes cron 任务名（与 configure_cron.py 默认值一致）
CRON_NAME = "mashiru-daily"
# Hermes 插件名（与 register_hermes_plugin.py 一致）
PLUGIN_NAME = "mashiru-daily"
# 项目内插件源目录与旧 skills 目录（相对 Server 根目录）
PLUGIN_SOURCE_DIR = "hermes_plugin/mashiru_daily"
LEGACY_SKILLS_DIR = "skills"
# webhook 路由名（与 configure_webhook.py 一致）
WEBHOOK_ROUTE = "todo-sync"

# 执行失败 / 需要用户手动操作 的汇总记录（main 末尾统一输出）
_FAILURES: list[str] = []
_ACTION_PROMPTS: list[str] = []


def venv_python(venv_dir: Path) -> Path:
    """返回虚拟环境内的解释器路径：Windows 为 Scripts/python.exe，其余平台为 bin/python。

    用字符串拼接而非 ``/`` 运算符，避免触发 pathlib 的 flavor 校验异常。
    """
    rel = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return Path(f"{venv_dir}/{rel}")


def _venv_site_packages(venv_dir: Path):
    """返回虚拟环境 site-packages 目录：Windows 为 Lib\\site-packages，POSIX 为
    lib/python*/site-packages；目录不存在时返回 None。"""
    if os.name == "nt":
        sp = venv_dir / "Lib" / "site-packages"
        return sp if sp.is_dir() else None
    for sp in (venv_dir / "lib").glob("python*/site-packages"):
        return sp
    return None


def _ensure_ruamel(venv_dir: Path) -> bool:
    """确保可导入 ruamel.yaml（config 清理的前置条件）。

    优先当前解释器；缺失时尝试注入虚拟环境的 site-packages（须在删除虚拟环境
    之前调用，故本函数在 main 开头执行一次）。仍不可用则返回 False，调用方
    跳过 config 步骤并提示手动清理。
    """
    try:
        import ruamel.yaml  # noqa: F401

        return True
    except ImportError:
        pass
    site_packages = _venv_site_packages(venv_dir)
    if site_packages is None:
        return False
    sys.path.insert(0, str(site_packages))
    try:
        import ruamel.yaml  # noqa: F401

        return True
    except ImportError:
        return False


def _remember_action_prompt(message: str) -> None:
    """打印一条要求用户手动操作的提示，并记录到程序末尾统一重放。"""
    print(message)
    _ACTION_PROMPTS.append(message)


def _confirm(message: str, yes: bool) -> bool:
    """确认提示：--yes 直接通过；否则读取 stdin，仅 y/yes 视为同意。

    经 builtins 引用 input 而非直接调用，使测试可经 monkeypatch 打补丁。
    """
    if yes:
        return True
    try:
        answer = builtins.input(f"{message} [y/N] ")
    except EOFError:
        return False
    return answer.strip().lower() in ("y", "yes")


def _is_link(path: Path) -> bool:
    """判断路径是否为符号链接或 Windows junction（目录联接点）。

    Path.is_symlink() 对 junction 返回 False（仅识别符号链接），故需额外检测
    is_junction（Python 3.12+）或 st_reparse_tag 兜底。
    """
    if path.is_symlink():
        return True
    if hasattr(path, "is_junction") and path.is_junction():
        return True
    try:
        return bool(getattr(path.lstat(), "st_reparse_tag", 0))
    except OSError:
        return False


# ---------------------------------------------------------------------------
# 步骤 1：停止运行中的服务器进程
# ---------------------------------------------------------------------------


def _stop_server(dry_run: bool, no_stop: bool) -> bool:
    """停止按命令行匹配 app.main 的服务器进程（按路径匹配，避免误杀无关进程）。"""
    if no_stop:
        print("[SKIP] 已跳过（--no-stop），运行中的服务器进程未被停止。")
        return True
    if os.name == "nt":
        cmd = [
            "powershell",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            "Get-CimInstance Win32_Process | Where-Object "
            "{ $_.CommandLine -like '*app.main*' -and $_.ProcessId -ne $PID } "
            "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force }",
        ]
    else:
        # pkill -f 按完整命令行匹配；返回 1（无匹配进程）属正常
        cmd = ["pkill", "-f", "app.main"]
    print(f"运行: {subprocess.list2cmdline(cmd)}")
    if dry_run:
        print("[DRY-RUN] 演练模式，跳过实际停止。")
        return True
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=60
        )
    except subprocess.TimeoutExpired:
        print("[FAIL] 停止服务器进程超时。", file=sys.stderr)
        return False
    if result.returncode not in (0, 1):
        print(f"[FAIL] 停止服务器进程失败（退出码 {result.returncode}）。", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        return False
    print("[OK] 服务器进程已停止（未匹配到进程则无需操作）。")
    return True


# ---------------------------------------------------------------------------
# 步骤 2：移除物理开机自启
# ---------------------------------------------------------------------------


def _remove_autostart(dry_run: bool, skip: bool) -> bool:
    """复用 install_autostart.py --uninstall 删除开机自启（Windows schtasks /
    systemd / crontab 由该脚本统一处理）。"""
    if skip:
        print("[SKIP] 已跳过（--skip-autostart）。")
        return True
    cmd = [sys.executable, "install_autostart.py", "--uninstall"]
    if dry_run:
        cmd.append("--dry-run")
    print(f"运行: {subprocess.list2cmdline(cmd)}")
    try:
        result = subprocess.run(
            cmd,
            cwd=str(SERVER_ROOT),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        print("[FAIL] 移除开机自启超时。", file=sys.stderr)
        return False
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip(), file=sys.stderr)
    if result.returncode != 0:
        print(f"[FAIL] 移除开机自启失败（退出码 {result.returncode}）。", file=sys.stderr)
        return False
    print("[OK] 开机自启移除完成。")
    return True


# ---------------------------------------------------------------------------
# 步骤 3：删除每日 Hermes cron 任务
# ---------------------------------------------------------------------------


def _remove_cron(dry_run: bool, skip: bool) -> bool:
    """幂等删除 cron 任务：hermes cron list --all 检查后按名 remove。

    hermes cron remove 接受任务名（大小写不敏感），无需先解析任务 ID。
    """
    if skip:
        print("[SKIP] 已跳过（--skip-cron）。")
        return True
    hermes = _config.find_hermes_exe()
    if hermes is None:
        _remember_action_prompt(
            "[提示] 找不到 hermes 可执行文件，请手动删除 cron 任务：hermes cron remove "
            + CRON_NAME
        )
        return True
    list_cmd = [hermes, "cron", "list", "--all"]
    remove_cmd = [hermes, "cron", "remove", CRON_NAME]
    print(f"运行: {subprocess.list2cmdline(list_cmd)}")
    if dry_run:
        print(f"将执行（演练）: {subprocess.list2cmdline(remove_cmd)}（若任务 {CRON_NAME} 存在）")
        return True
    result = _config.run_command(list_cmd, timeout=60)
    if result.returncode != 0:
        print("[FAIL] hermes cron list 执行失败，无法判断任务是否存在。", file=sys.stderr)
        print((result.stderr or result.stdout or "").strip(), file=sys.stderr)
        return False
    output = (result.stdout or "") + (result.stderr or "")
    if output.strip():
        print(output.strip())
    # 按 cron list 输出的 Name: 行精确匹配任务名（词边界），防同名前缀误判
    name_re = re.compile(rf"^\s*Name:\s+{re.escape(CRON_NAME)}(\s|$)")
    if not any(name_re.search(line) for line in output.splitlines()):
        print(f"[SKIP] cron 任务 {CRON_NAME} 不存在，无需删除。")
        return True
    print(f"运行: {subprocess.list2cmdline(remove_cmd)}")
    result = _config.run_command(remove_cmd, timeout=60)
    if result.returncode != 0:
        print(f"[FAIL] 删除 cron 任务 {CRON_NAME} 失败。", file=sys.stderr)
        print((result.stderr or result.stdout or "").strip(), file=sys.stderr)
        return False
    print(f"[OK] cron 任务 {CRON_NAME} 已删除。")
    return True


# ---------------------------------------------------------------------------
# 步骤 4：清理 webhook 配置（config.yaml + 网关重启）
# ---------------------------------------------------------------------------


def _restart_gateway() -> bool:
    """重启 Hermes 网关使 webhook 路由失效；复用 configure_webhook 的降级逻辑。"""
    hermes = _config.find_hermes_exe()
    if hermes is None:
        _remember_action_prompt("[提示] 找不到 hermes 可执行文件，请手动重启网关：hermes gateway restart")
        return True
    print("正在重启 Hermes 网关（todo-sync 路由已移除，重启后生效）...")
    rc = configure_webhook._restart_gateway(hermes)
    if rc == 1:
        _remember_action_prompt("[提示] 网关重启失败，webhook 路由可能仍存活，请手动执行：hermes gateway restart")
        return False
    if rc in (2, 3):
        # 良性降级：config 已写入、仅重启受限（root 拒绝刷新 systemd 单元等）
        _remember_action_prompt(
            "[提示] Hermes 拒绝在当前环境重启网关（config 已清理），"
            "todo-sync 路由将在 Hermes 下次重启时失效。"
        )
    return True


def _remove_webhook_config(dry_run: bool, skip: bool, no_restart: bool, ruamel_ok: bool) -> bool:
    """从 config.yaml 移除 platforms.webhook 的 todo-sync 路由。

    其它平台（如 qqbot）与既有路由一律保留；仅当 webhook 块是本次工具产物
    （routes 已空、extra 只剩 port、无全局 secret）时整块删除。修改前备份。
    """
    if skip:
        print("[SKIP] 已跳过（--skip-webhook）。")
        return True
    if not ruamel_ok:
        _remember_action_prompt(
            "[提示] ruamel.yaml 不可用，请手动从 config.yaml 的 "
            "platforms.webhook.extra.routes 中删除 todo-sync 路由。"
        )
        return True
    config_path = _config.get_config_path()
    if not config_path.is_file():
        print("[SKIP] 未找到 config.yaml，无需清理 webhook 配置。")
        return True
    yaml_obj = _config.new_yaml()
    data = _config.load_config(yaml_obj, config_path)

    changed = False
    platforms = data.get("platforms")
    if isinstance(platforms, dict):
        webhook = platforms.get("webhook")
        if isinstance(webhook, dict):
            extra = webhook.get("extra")
            routes = extra.get("routes") if isinstance(extra, dict) else None
            if isinstance(routes, dict) and WEBHOOK_ROUTE in routes:
                del routes[WEBHOOK_ROUTE]
                changed = True
                if not routes:
                    del extra["routes"]
                # routes 已清空且 extra 只剩本工具设置的 port（无全局 secret / 其它键）
                # → 整块 webhook 是本次工具创建，一并删除；否则保留其余配置
                extra_keys = set(extra.keys()) if isinstance(extra, dict) else set()
                if extra_keys <= {"port"}:
                    del platforms["webhook"]
        if not platforms:
            del data["platforms"]

    if not changed:
        print("[SKIP] config.yaml 中无 todo-sync webhook 路由，无需清理。")
        return True
    if dry_run:
        print("将删除（演练）: platforms.webhook 中的 todo-sync 路由。")
        if not no_restart:
            hermes = _config.find_hermes_exe()
            restart_cmd = "hermes gateway restart" if hermes is None else f"{hermes} gateway restart"
            print(f"将执行（演练）: {restart_cmd}")
        return True

    backup_path = _config.backup_config(config_path)
    print(f"[OK] 修改前已备份原配置到 {backup_path}")
    _config.dump_config(yaml_obj, data, config_path)
    print("[OK] 已从 config.yaml 移除 todo-sync webhook 路由。")
    if no_restart:
        hermes = _config.find_hermes_exe()
        restart_cmd = "hermes gateway restart" if hermes is None else f"{hermes} gateway restart"
        _remember_action_prompt(f"[提示] 路由已移除但网关未重启（--no-restart），请手动执行：{restart_cmd}")
        return True
    return _restart_gateway()


# ---------------------------------------------------------------------------
# 步骤 5：移除 Hermes 插件注册
# ---------------------------------------------------------------------------


def _cleanup_plugin_config(dry_run: bool, ruamel_ok: bool) -> bool:
    """从 config.yaml 移除 plugins.enabled 中的插件名与 skills.external_dirs
    中的本工具路径（新 skills 目录与旧 Server/skills 迁移路径）。"""
    if not ruamel_ok:
        _remember_action_prompt(
            "[提示] ruamel.yaml 不可用，请手动从 config.yaml 删除 mashiru-daily "
            "相关条目（plugins.enabled / skills.external_dirs）。"
        )
        return True
    config_path = _config.get_config_path()
    if not config_path.is_file():
        print("[SKIP] 未找到 config.yaml，无需清理插件配置。")
        return True
    yaml_obj = _config.new_yaml()
    data = _config.load_config(yaml_obj, config_path)

    changed = False
    plugins = data.get("plugins")
    if isinstance(plugins, dict):
        enabled = plugins.get("enabled")
        if isinstance(enabled, list) and PLUGIN_NAME in enabled:
            enabled[:] = [item for item in enabled if item != PLUGIN_NAME]
            changed = True
            if not enabled:
                del plugins["enabled"]
        if not plugins:
            del data["plugins"]
    skills = data.get("skills")
    if isinstance(skills, dict):
        external_dirs = skills.get("external_dirs")
        if isinstance(external_dirs, list):
            new_dir = _config.forward_slashes(SERVER_ROOT / PLUGIN_SOURCE_DIR / "skills")
            legacy_dir = _config.forward_slashes(SERVER_ROOT / LEGACY_SKILLS_DIR)
            kept = [
                item for item in external_dirs
                if str(item).replace("\\", "/") not in (new_dir, legacy_dir)
            ]
            if len(kept) != len(external_dirs):
                if kept:
                    external_dirs[:] = kept
                else:
                    del skills["external_dirs"]
                changed = True
        if not skills:
            del data["skills"]

    if not changed:
        print("[SKIP] config.yaml 中无 mashiru-daily 插件条目，无需清理。")
        return True
    if dry_run:
        print("[DRY-RUN] 将删除（演练）: plugins.enabled 中的 mashiru-daily 与 "
              "skills.external_dirs 中的本工具路径。")
        return True
    backup_path = _config.backup_config(config_path)
    print(f"[OK] 修改前已备份原配置到 {backup_path}")
    _config.dump_config(yaml_obj, data, config_path)
    print("[OK] 已从 config.yaml 清理 mashiru-daily 插件注册。")
    return True


def _remove_plugin_link(dry_run: bool) -> bool:
    """删除 $HERMES_HOME/plugins/mashiru-daily 链接（junction / symlink）。

    安全纪律：仅当目标是指向本插件源目录的链接时才删除；真实目录或指向其它
    位置的链接一律跳过并警告，绝不删除用户数据。junction 用 cmd rmdir 删除
    接合点本身（不递归目标），symlink 用 unlink。
    """
    target = _config.get_hermes_home() / "plugins" / PLUGIN_NAME
    source = SERVER_ROOT / PLUGIN_SOURCE_DIR
    if not (target.exists() or _is_link(target)):
        print(f"[SKIP] Hermes 插件链接 {target} 不存在，无需删除。")
        return True
    if not _is_link(target):
        print(f"[WARN] {target} 是真实目录（非链接），跳过不删除，请人工确认。", file=sys.stderr)
        return True
    try:
        points_to_source = target.resolve() == source.resolve()
    except OSError:
        points_to_source = False
    if not points_to_source:
        print(f"[WARN] {target} 是链接但指向其他位置（非 {source}），跳过不删除。", file=sys.stderr)
        return True
    if dry_run:
        print(f"将删除（演练）: 插件链接 {target} -> {source}")
        return True
    if target.is_symlink():
        target.unlink()
        print(f"[OK] 已删除插件链接 {target}。")
        return True
    # Windows junction：cmd rmdir 仅删除接合点本身，绝不递归目标目录
    result = _config.run_command(["cmd", "/c", "rmdir", str(target)], timeout=30)
    if result.returncode != 0:
        print(f"[FAIL] 删除插件接合点失败：{(result.stderr or '').strip()}", file=sys.stderr)
        return False
    print(f"[OK] 已删除插件接合点 {target}。")
    return True


def _remove_plugin(dry_run: bool, skip: bool, ruamel_ok: bool) -> bool:
    """移除 Hermes 插件注册：CLI disable（尽力而为）→ config.yaml 清理 → 链接删除。"""
    if skip:
        print("[SKIP] 已跳过（--skip-plugin）。")
        return True
    ok = True
    hermes = _config.find_hermes_exe()
    if hermes is not None:
        disable_cmd = [hermes, "plugins", "disable", PLUGIN_NAME]
        print(f"运行: {subprocess.list2cmdline(disable_cmd)}")
        if not dry_run:
            result = _config.run_command(disable_cmd, timeout=60)
            if result.returncode != 0:
                print("[WARN] hermes plugins disable 执行失败，将继续清理 config.yaml。", file=sys.stderr)
    elif not dry_run:
        print("[SKIP] 找不到 hermes 可执行文件，跳过 CLI 禁用（config.yaml 仍会被清理）。")
    if not _cleanup_plugin_config(dry_run, ruamel_ok):
        ok = False
    if not _remove_plugin_link(dry_run):
        ok = False
    return ok


# ---------------------------------------------------------------------------
# 步骤 6/7：删除虚拟环境与数据目录
# ---------------------------------------------------------------------------


def _remove_venv(dry_run: bool, keep: bool, venv_dir: Path) -> bool:
    """删除虚拟环境目录。"""
    if keep:
        print(f"[SKIP] 已保留虚拟环境（--keep-venv）：{venv_dir}")
        return True
    if not venv_dir.is_dir():
        print(f"[SKIP] 虚拟环境 {venv_dir} 不存在，无需删除。")
        return True
    if dry_run:
        print(f"将删除（演练）: 虚拟环境 {venv_dir}")
        return True
    try:
        shutil.rmtree(venv_dir)
    except OSError as exc:
        print(f"[FAIL] 删除虚拟环境失败：{exc}", file=sys.stderr)
        _remember_action_prompt(f"[提示] 请确认无进程占用后手动删除虚拟环境：{venv_dir}")
        return False
    print(f"[OK] 虚拟环境已删除：{venv_dir}")
    return True


def _remove_data(dry_run: bool, keep: bool, yes: bool) -> bool:
    """删除数据目录（todo.json / todo-meta.json / plan.md / backups）。"""
    data_dir = Path(os.environ.get("MASHIRU_DATA_DIR", str(SERVER_ROOT / "data")))
    if keep:
        print(f"[SKIP] 已保留数据目录（--keep-data）：{data_dir}")
        return True
    if not data_dir.is_dir():
        print(f"[SKIP] 数据目录 {data_dir} 不存在，无需删除。")
        return True
    if not _confirm(
        f"确认删除数据目录 {data_dir}（含 todo.json / todo-meta.json / plan.md / backups）？",
        yes,
    ):
        print("[取消] 数据目录保留。")
        return True
    if dry_run:
        print(f"将删除（演练）: 数据目录 {data_dir}")
        return True
    try:
        shutil.rmtree(data_dir)
    except OSError as exc:
        print(f"[FAIL] 删除数据目录失败：{exc}", file=sys.stderr)
        return False
    print(f"[OK] 数据目录已删除：{data_dir}")
    return True


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def _run(args: argparse.Namespace) -> int:
    """按序执行七个卸载步骤；步骤相互独立、尽力而为，失败聚合后返回非零。"""
    venv_dir = SERVER_ROOT / args.venv
    # ruamel 探测必须在删除虚拟环境之前完成（可能从 venv site-packages 注入）
    ruamel_ok = _ensure_ruamel(venv_dir)
    if not ruamel_ok:
        _remember_action_prompt(
            "[提示] 未找到 ruamel.yaml（当前解释器与虚拟环境均不可用），"
            "config.yaml 相关清理步骤已跳过，请安装后重跑或手动清理。"
        )

    steps = [
        ("停止运行中的服务器进程", lambda: _stop_server(args.dry_run, args.no_stop)),
        ("移除物理开机自启", lambda: _remove_autostart(args.dry_run, args.skip_autostart)),
        ("删除每日 Hermes cron 任务", lambda: _remove_cron(args.dry_run, args.skip_cron)),
        (
            "清理 webhook 配置",
            lambda: _remove_webhook_config(args.dry_run, args.skip_webhook, args.no_restart, ruamel_ok),
        ),
        (
            "移除 Hermes 插件注册",
            lambda: _remove_plugin(args.dry_run, args.skip_plugin, ruamel_ok),
        ),
        ("删除虚拟环境", lambda: _remove_venv(args.dry_run, args.keep_venv, venv_dir)),
        ("删除数据目录", lambda: _remove_data(args.dry_run, args.keep_data, args.yes)),
    ]
    for i, (title, step) in enumerate(steps, 1):
        print(f"\n[{i}/{len(steps)}] {title}")
        if not step():
            _FAILURES.append(title)
    return 1 if _FAILURES else 0


def _print_summary() -> None:
    """程序末尾统一输出失败步骤与要求用户手动完成的操作提示。"""
    print("\n" + "=" * 60)
    if _FAILURES:
        print("以下步骤执行失败，请检查后重试或手动处理：")
        for i, title in enumerate(_FAILURES, 1):
            print(f"{i}. {title}")
    else:
        print("[完成] 卸载流程已结束。")
    if _ACTION_PROMPTS:
        print("\n以下操作需要您手动完成，请勿遗漏：")
        for i, prompt in enumerate(_ACTION_PROMPTS, 1):
            print(f"{i}. {prompt}")
    print("=" * 60)


def main(argv: list[str] | None = None) -> int:
    """解析参数并执行卸载流程；返回退出码（不抛出 SystemExit）。"""
    parser = argparse.ArgumentParser(
        description="MashiruDaily.Server 一键卸载：移除虚拟环境、数据目录、开机自启、cron 任务、webhook 配置与 Hermes 插件注册（保留源码）"
    )
    parser.add_argument("--venv", default=".venv", help="虚拟环境目录名（默认 .venv）")
    parser.add_argument("--dry-run", action="store_true", help="演练：只打印将执行的命令，不实际执行")
    parser.add_argument("--yes", "-y", action="store_true", help="跳过所有确认提示（默认删除数据目录前需确认）")
    parser.add_argument("--keep-data", action="store_true", help="保留数据目录 data/")
    parser.add_argument("--keep-venv", action="store_true", help="保留虚拟环境 .venv")
    parser.add_argument("--no-stop", action="store_true", help="不停止运行中的服务器进程")
    parser.add_argument("--no-restart", action="store_true", help="不自动重启 Hermes 网关（仅打印命令）")
    parser.add_argument("--skip-autostart", action="store_true", help="跳过移除开机自启")
    parser.add_argument("--skip-cron", action="store_true", help="跳过删除 cron 任务")
    parser.add_argument("--skip-webhook", action="store_true", help="跳过清理 webhook 配置")
    parser.add_argument("--skip-plugin", action="store_true", help="跳过移除插件注册")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    _FAILURES.clear()
    _ACTION_PROMPTS.clear()
    try:
        return _run(args)
    finally:
        _print_summary()
        _FAILURES.clear()
        _ACTION_PROMPTS.clear()


if __name__ == "__main__":
    sys.exit(main())
