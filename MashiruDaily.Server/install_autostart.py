"""注册/管理 MashiruDailyServer（拉取服务器）的开机自启（幂等，跨平台）。

平台分派：
- Windows：注册表 HKCU\\...\\Run 登录自启（pythonw.exe 无控制台窗口；免管理员权限——
  schtasks 的 ONLOGON/ONSTART 触发器需要提权，普通用户会报 Access denied）；
- Linux/macOS：优先 systemd 用户服务（支持崩溃自动重启、开机自启），
  无 systemd 时回退 crontab @reboot（macOS 无 systemctl，天然走 crontab 兜底）。

用法：
    .venv\\Scripts\\python.exe install_autostart.py              # 注册自启
    .venv\\Scripts\\python.exe install_autostart.py --disable    # 临时禁用
    .venv\\Scripts\\python.exe install_autostart.py --enable     # 重新启用
    .venv\\Scripts\\python.exe install_autostart.py --uninstall  # 删除自启
    .venv\\Scripts\\python.exe install_autostart.py --dry-run    # 只打印将执行的命令，不实际执行
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

TASK_NAME = "MashiruDailyServer"
SERVICE_NAME = "mashirudaily-server.service"

# Windows 注册表 Run 键（禁用态后缀）
_RUN_KEY_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_DISABLED_SUFFIX = "_DISABLED"

# crontab 行的唯一标记（用于幂等判断与 disable/enable）
_CRON_MARKER = "# mashirudaily-server"
_CRON_DISABLED_MARKER = "# mashirudaily-server(DISABLED)"


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _run(cmd, action_desc: str, timeout: int = 60, dry_run: bool = False) -> int:
    """执行子进程命令并打印结果，返回退出码；--dry-run 时只打印不执行。"""
    print(f"运行: {subprocess.list2cmdline(cmd)}")
    if dry_run:
        print(f"[DRY-RUN] 跳过执行（--dry-run）。")
        return 0
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, errors="replace", timeout=timeout
        )
    except subprocess.TimeoutExpired:
        print(f"[FAIL] {action_desc}超时。", file=sys.stderr)
        return 1
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.returncode != 0:
        print(f"[FAIL] {action_desc}失败（退出码 {result.returncode}）。", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        return 1
    print(f"[OK] {action_desc}成功。")
    return 0


def _venv_python() -> Path:
    """返回虚拟环境内的解释器路径（Windows 用 pythonw 免控制台窗口，POSIX 用 python）。"""
    server_root = Path(__file__).resolve().parent
    if os.name == "nt":
        py = server_root / ".venv" / "Scripts" / "pythonw.exe"
    else:
        py = server_root / ".venv" / "bin" / "python"
    if not py.is_file():
        print(f"[WARN] 未找到 {py}，请先运行 setup_server.py 创建虚拟环境，否则自启将无法启动服务。")
    return py


# ---------------------------------------------------------------------------
# Windows：注册表 HKCU\...\Run（免管理员）
# ---------------------------------------------------------------------------


def _run_value() -> str:
    """生成 Run 键值：""<pythonw.exe>" -m app.main"。"""
    return f'"{_venv_python()}" -m app.main'


def _run_key_state() -> tuple:
    """读取 Run 键当前状态，返回 (值名, 值内容)；未注册返回 (None, None)。

    禁用态以值名后缀 _DISABLED 标记（Run 键不识别该名，登录时不执行）。
    """
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH) as key:
            for name in (TASK_NAME, TASK_NAME + _RUN_DISABLED_SUFFIX):
                try:
                    value, _ = winreg.QueryValueEx(key, name)
                    return name, value
                except FileNotFoundError:
                    continue
    except OSError as exc:
        print(f"[WARN] 读取注册表 Run 键失败：{exc}", file=sys.stderr)
    return None, None


def _set_run_value(name: str, value: str) -> None:
    """写入 Run 键值（创建键不存在时）。"""
    import winreg

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH) as key:
        winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)


def _delete_run_value(name: str) -> None:
    """删除 Run 键值。"""
    import winreg

    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY_PATH, 0, winreg.KEY_SET_VALUE) as key:
        winreg.DeleteValue(key, name)


def _install_windows(args) -> int:
    import winreg

    if args.uninstall:
        name, _ = _run_key_state()
        if name is None:
            print(f"[SKIP] 注册表 Run 键中不存在 {TASK_NAME}，无需删除。")
            return 0
        if args.dry_run:
            print(f"[DRY-RUN] 将删除注册表 Run 值 {name}。")
            return 0
        _delete_run_value(name)
        print(f"[OK] 已删除注册表 Run 值 {name}。")
        return 0

    if args.disable or args.enable:
        name, _ = _run_key_state()
        if name is None:
            print(f"[FAIL] 注册表 Run 键中不存在 {TASK_NAME}，请先运行默认（注册）模式。", file=sys.stderr)
            return 1
        if args.disable:
            if name.endswith(_RUN_DISABLED_SUFFIX):
                print(f"[SKIP] 自启已处于禁用状态，无需修改。")
                return 0
            if args.dry_run:
                print(f"[DRY-RUN] 将把 Run 值 {name} 重命名为 {TASK_NAME + _RUN_DISABLED_SUFFIX}（禁用）。")
                return 0
            _delete_run_value(name)
            _set_run_value(TASK_NAME + _RUN_DISABLED_SUFFIX, _run_value())
            print(f"[OK] 已禁用自启（值名改为 {TASK_NAME + _RUN_DISABLED_SUFFIX}，登录时不执行）。")
            return 0
        # enable
        if not name.endswith(_RUN_DISABLED_SUFFIX):
            print(f"[SKIP] 自启已处于启用状态，无需修改。")
            return 0
        if args.dry_run:
            print(f"[DRY-RUN] 将把 Run 值 {name} 恢复为 {TASK_NAME}（启用）。")
            return 0
        _delete_run_value(name)
        _set_run_value(TASK_NAME, _run_value())
        print(f"[OK] 已启用自启（值名恢复为 {TASK_NAME}）。")
        return 0

    # 默认：注册登录自启
    name, value = _run_key_state()
    if name is not None and not name.endswith(_RUN_DISABLED_SUFFIX):
        print(f"[SKIP] 自启已注册：{name} = {value}，无需重复写入。")
        return 0
    print(f"[INFO] 注册表 Run 值：{TASK_NAME} = {_run_value()}")
    if args.dry_run:
        print("[DRY-RUN] 跳过写入注册表。")
        return 0
    _set_run_value(TASK_NAME, _run_value())
    print("[OK] 已写入注册表 Run 键（登录时自动启动）。")
    return 0


# ---------------------------------------------------------------------------
# Linux/macOS：systemd 用户服务（优先）
# ---------------------------------------------------------------------------


def _systemd_available() -> bool:
    """判断 systemd 用户实例是否可用（无 systemctl 或非 systemd 环境返回 False）。"""
    if shutil.which("systemctl") is None:
        return False
    try:
        result = subprocess.run(
            ["systemctl", "--user", "show-environment"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=15,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def _service_unit_path() -> Path:
    """返回 systemd 用户服务单元文件路径（~/.config/systemd/user/）。"""
    return Path.home() / ".config" / "systemd" / "user" / SERVICE_NAME


def _service_unit_content() -> str:
    """生成 systemd 用户服务单元内容：开机自启、崩溃自动重启、网络就绪后启动。"""
    server_root = Path(__file__).resolve().parent
    python = _venv_python()
    return (
        "[Unit]\n"
        "Description=MashiruDaily Server (拉取服务器)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={server_root}\n"
        f"ExecStart={python} -m app.main\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=default.target\n"
    )


def _install_systemd(args) -> int:
    unit_path = _service_unit_path()
    if args.uninstall:
        if not unit_path.is_file():
            print(f"[SKIP] 服务单元 {SERVICE_NAME} 不存在，无需删除。")
            return 0
        rc = _run(["systemctl", "--user", "disable", SERVICE_NAME], "禁用自启（disable）", dry_run=args.dry_run)
        if rc != 0:
            return rc
        if args.dry_run:
            print(f"[DRY-RUN] 将删除单元文件 {unit_path}")
            return 0
        unit_path.unlink(missing_ok=True)
        return _run(["systemctl", "--user", "daemon-reload"], "重载 systemd 配置")

    if args.disable or args.enable:
        if not unit_path.is_file():
            print(f"[FAIL] 服务单元 {SERVICE_NAME} 不存在，请先运行默认（注册）模式。", file=sys.stderr)
            return 1
        verb = "disable" if args.disable else "enable"
        return _run(
            ["systemctl", "--user", verb, SERVICE_NAME],
            ("禁用自启（disable）" if args.disable else "启用自启（enable）"),
            dry_run=args.dry_run,
        )

    # 默认：安装服务单元 + 启用 + 立即启动（--now 便于验证）
    if args.dry_run:
        print(f"[DRY-RUN] 将写入单元文件 {unit_path}：\n{_service_unit_content()}")
    else:
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(_service_unit_content(), encoding="utf-8")
        print(f"[OK] 已写入单元文件 {unit_path}")
    rc = _run(
        ["systemctl", "--user", "enable", "--now", SERVICE_NAME],
        "启用并启动服务（enable --now）",
        dry_run=args.dry_run,
    )
    if rc != 0:
        return rc
    if args.dry_run:
        return 0
    return _run(["systemctl", "--user", "status", SERVICE_NAME, "--no-pager"], "校验服务状态")


# ---------------------------------------------------------------------------
# Linux/macOS 兜底：crontab @reboot
# ---------------------------------------------------------------------------


def _read_crontab() -> list:
    """读取当前 crontab 内容（无任务时为空列表）。"""
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, errors="replace", timeout=30
        )
    except subprocess.TimeoutExpired:
        print("[FAIL] 读取 crontab 超时。", file=sys.stderr)
        raise
    if result.returncode != 0 and "no crontab" not in (result.stderr or "").lower():
        print(f"[FAIL] 读取 crontab 失败（退出码 {result.returncode}）。", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        raise RuntimeError("crontab -l 失败")
    return [line for line in (result.stdout or "").splitlines() if line.strip()]


def _write_crontab(lines: list) -> int:
    """将行列表写回 crontab（stdin 模式），返回退出码（0 成功）。"""
    try:
        result = subprocess.run(
            ["crontab", "-"], input="\n".join(lines) + "\n", capture_output=True,
            text=True, errors="replace", timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("[FAIL] 写入 crontab 超时。", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print(f"[FAIL] 写入 crontab 失败（退出码 {result.returncode}）。", file=sys.stderr)
        if result.stderr.strip():
            print(result.stderr.strip(), file=sys.stderr)
        return 1
    return 0


def _cron_line(enabled: bool) -> str:
    """生成（或按 enabled 转换）@reboot 自启行，尾部带唯一标记。"""
    server_root = Path(__file__).resolve().parent
    python = _venv_python()
    marker = _CRON_MARKER if enabled else _CRON_DISABLED_MARKER
    return f"@reboot cd {server_root} && {python} -m app.main >> {server_root / 'data' / 'autostart.log'} 2>&1 {marker}"


def _find_cron_line(lines: list) -> tuple:
    """在行列表中查找自启行，返回 (行索引, 是否启用)；未找到返回 (None, None)。

    注意：禁用标记是启用标记的子串，必须先匹配更长的禁用标记，否则禁用行会被误判为启用。
    """
    for idx, line in enumerate(lines):
        if _CRON_DISABLED_MARKER in line:
            return idx, False
        if _CRON_MARKER in line:
            return idx, True
    return None, None


def _install_crontab(args) -> int:
    try:
        lines = _read_crontab()
    except RuntimeError:
        return 1

    if args.uninstall:
        idx, _ = _find_cron_line(lines)
        if idx is None:
            print(f"[SKIP] crontab 中未找到自启行，无需删除。")
            return 0
        removed = lines.pop(idx)
        print(f"[INFO] 删除行：{removed}")
        if args.dry_run:
            print("[DRY-RUN] 跳过写入 crontab。")
            return 0
        return _write_crontab(lines)

    if args.disable or args.enable:
        idx, enabled = _find_cron_line(lines)
        if idx is None:
            print(f"[FAIL] crontab 中未找到自启行，请先运行默认（注册）模式。", file=sys.stderr)
            return 1
        want_enabled = not args.disable
        if enabled == want_enabled:
            print(f"[SKIP] 自启行已处于{'启用' if enabled else '禁用'}状态，无需修改。")
            return 0
        lines[idx] = _cron_line(want_enabled)
        if args.dry_run:
            print(f"[DRY-RUN] 将替换为：{lines[idx]}")
            return 0
        return _write_crontab(lines)

    # 默认：追加 @reboot 自启行（已存在则跳过，幂等）
    idx, enabled = _find_cron_line(lines)
    if idx is not None:
        print(f"[SKIP] crontab 已存在自启行（{'启用' if enabled else '禁用'}状态）。")
        return 0
    new_line = _cron_line(enabled=True)
    print(f"[INFO] 追加行：{new_line}")
    if args.dry_run:
        print("[DRY-RUN] 跳过写入 crontab。")
        return 0
    return _write_crontab(lines + [new_line])


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="注册/管理 MashiruDailyServer（拉取服务器）的开机自启（Windows: 注册表 Run；Linux/macOS: systemd 或 crontab）"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--uninstall", action="store_true", help="删除自启")
    group.add_argument("--disable", action="store_true", help="禁用自启（不删除）")
    group.add_argument("--enable", action="store_true", help="启用自启")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不实际执行")
    args = parser.parse_args()

    if os.name == "nt":
        # Windows：注册表 HKCU Run 键（免管理员；schtasks ONLOGON 需提权，非管理员会 Access denied）
        return _install_windows(args)

    # POSIX（Linux/macOS）：优先 systemd 用户服务，不可用时回退 crontab
    if not args.dry_run and _systemd_available():
        print(f"[INFO] 检测到 systemd 用户实例，使用 systemd 用户服务（{SERVICE_NAME}）。")
        return _install_systemd(args)

    print("[INFO] 未检测到 systemd（或 --dry-run），回退 crontab @reboot 方式。")
    return _install_crontab(args)


if __name__ == "__main__":
    sys.exit(main())
