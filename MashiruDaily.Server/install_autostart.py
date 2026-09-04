"""注册/管理 MashiruDailyServer（拉取服务器）的【物理开机自启】（幂等，跨平台）。

平台分派：
- Windows：schtasks /SC ONSTART + /RU SYSTEM（系统启动即触发、无需登录，SYSTEM 账户免密码）。
- Linux/macOS：优先 systemd 系统服务（/etc/systemd/system，WantedBy=multi-user.target，
  物理开机自启 + 崩溃自动重启 + 网络就绪后启动）。需要 root/sudo；脚本在非 root 时自动加 sudo 前缀。
  无 systemd（或 macOS）时回退 crontab @reboot（cron 守护进程开机即执行，无需登录、免 sudo）。

说明：物理开机启动属于系统级能力，必然要求管理员/sudo（OS 安全模型）；
免提权的轻量替代是 crontab @reboot（无崩溃自动重启与依赖排序，但同样满足物理开机）。

退出码：0=成功或无需操作；1=失败；2=Windows 非管理员，未执行、需用户手动完成
（bootstrap/uninstall 据此提示用户手动操作，不中断流程）。

用法：
    .venv\\Scripts\\python.exe install_autostart.py              # 注册物理开机自启
    .venv\\Scripts\\python.exe install_autostart.py --disable    # 临时禁用（不删除）
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

# Windows 非管理员运行时的退出码：表示未执行、需要用户手动完成（调用方据此提示，不判失败）
EXIT_MANUAL_REQUIRED = 2

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
        print("[DRY-RUN] 跳过执行（--dry-run）。")
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
    server_root = _server_root()
    if os.name == "nt":
        py = server_root / ".venv" / "Scripts" / "pythonw.exe"
    else:
        py = server_root / ".venv" / "bin" / "python"
    if not py.is_file():
        print(f"[WARN] 未找到 {py}，请先运行 setup_server.py 创建虚拟环境，否则自启将无法启动服务。")
    return py


def _server_root() -> Path:
    """返回本脚本所在目录（即 MashiruDaily.Server 根目录）。"""
    return Path(__file__).resolve().parent


# ---------------------------------------------------------------------------
# Windows：schtasks ONSTART（系统启动即运行，SYSTEM 账户，免登录）
# ---------------------------------------------------------------------------


def _is_admin_win() -> bool:
    """判断当前进程是否已具备管理员权限（非管理员时打印手动指引，不自动提权）。"""
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def _print_manual_instructions(args) -> None:
    """Windows 非管理员时打印手动操作指引（不尝试自动 UAC 提权）。

    自动提权（ShellExecuteW runas）在受限/非交互会话下会静默失败且没有返回值检查，
    用户感知为「没有弹窗、什么都没发生」；因此改为打印可复制的管理员操作指引，
    并返回 EXIT_MANUAL_REQUIRED，由用户或调用方（bootstrap/uninstall）手动完成。
    """
    if args.uninstall:
        verb = "删除开机自启"
    elif args.disable:
        verb = "禁用开机自启"
    elif args.enable:
        verb = "启用开机自启"
    else:
        verb = "注册开机自启"
    script = Path(sys.argv[0]).resolve()
    rerun_cmd = subprocess.list2cmdline([sys.executable, str(script)] + sys.argv[1:])
    print(f"[INFO] {verb}需要管理员权限（schtasks 属系统级计划任务，任务以 SYSTEM 账户运行）。")
    print("[INFO] 本程序不自动弹出 UAC 授权（受限/非交互会话下可能静默失败），请手动完成：")
    print("  1) 按 Win+X 选择「终端(管理员)」，或搜索 PowerShell 后右键「以管理员身份运行」；")
    print("     出现 UAC 弹窗时选择「是」；")
    print("  2) 在管理员终端中执行以下命令：")
    print(f"     {rerun_cmd}")


def _schtasks_exists() -> bool:
    """查询计划任务是否存在（用退出码判断，与本地化报错文本无关）。"""
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        print("[WARN] 查询计划任务超时，按不存在处理。", file=sys.stderr)
        return False
    return result.returncode == 0


def _win_task_command() -> str:
    """构造 schtasks /TR 的启动命令

    pythonw 无控制台时 sys.stdout/sys.stderr 为 None，
    uvicorn 默认日志格式器会调用 sys.stdout.isatty() 抛 AttributeError，
    导致进程启动即退出（计划任务上次结果 = 1）。重定向到文件后服务才能常驻。
    """
    root = _server_root()
    pythonw = _venv_python()
    if " " in str(root) or " " in str(pythonw):
        print(
            "[FAIL] 项目路径含空格，schtasks /TR 嵌套引号不可靠。请将项目迁移到无空格路径后重试。",
            file=sys.stderr,
        )
        raise SystemExit(1)
    log_path = root / "autostart.log"
    return f"cmd /c cd /d {root} && {pythonw} -m app.main >> {log_path} 2>&1"


def _install_windows(args) -> int:
    if args.uninstall:
        if not _schtasks_exists():
            print(f"[SKIP] 计划任务 {TASK_NAME} 不存在，无需删除。")
            return 0
        return _run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], "删除自启任务", dry_run=args.dry_run)

    if args.disable or args.enable:
        if not _schtasks_exists():
            print(f"[FAIL] 计划任务 {TASK_NAME} 不存在，请先运行默认（注册）模式。", file=sys.stderr)
            return 1
        flag = "/DISABLE" if args.disable else "/ENABLE"
        return _run(
            ["schtasks", "/Change", "/TN", TASK_NAME, flag],
            "禁用自启任务" if args.disable else "启用自启任务",
            dry_run=args.dry_run,
        )

    # 默认：注册 ONSTART 任务（系统启动即运行；/RU SYSTEM 无需登录、免密码）
    task_run = _win_task_command()
    print(f"[INFO] 计划任务命令（开机自启，SYSTEM 账户）：{task_run}")
    rc = _run(
        [
            "schtasks",
            "/Create",
            "/TN", TASK_NAME,
            "/TR", task_run,
            "/SC", "ONSTART",
            "/RU", "SYSTEM",
            "/F",
        ],
        "注册开机自启任务（ONSTART + SYSTEM）",
        dry_run=args.dry_run,
    )
    if rc != 0:
        return rc
    # 创建后校验（dry-run 时跳过真实查询）
    if args.dry_run:
        return 0
    return _run(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"], "校验任务状态")


# ---------------------------------------------------------------------------
# Linux/macOS：systemd 系统服务（物理开机自启，需 root/sudo）
# ---------------------------------------------------------------------------


def _systemd_available() -> bool:
    """判断 systemd 是否为主 init（/run/systemd/system 存在且 systemctl 可用）。"""
    return Path("/run/systemd/system").exists() and shutil.which("systemctl") is not None


def _service_unit_path() -> Path:
    """返回 systemd 系统服务单元文件路径（/etc/systemd/system/，物理开机自启）。"""
    return Path("/etc/systemd/system") / SERVICE_NAME


def _service_unit_content() -> str:
    """生成 systemd 服务单元：multi-user.target 开机启动、崩溃自动重启、网络就绪后启动。"""
    python = _venv_python()
    return (
        "[Unit]\n"
        "Description=MashiruDaily Server (拉取服务器)\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"WorkingDirectory={_server_root()}\n"
        f"ExecStart={python} -m app.main\n"
        "Restart=on-failure\n"
        "RestartSec=5\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def _with_sudo(cmd: list) -> list:
    """root 直接执行；非 root 时若 sudo 可用则加前缀，否则返回 None。"""
    if os.geteuid() == 0:
        return cmd
    if shutil.which("sudo"):
        return ["sudo"] + cmd
    print(
        "[FAIL] 需要 root 或 sudo 才能管理系统服务；当前用户无 sudo 权限。"
        "可改用 crontab 方式（无 systemd 时自动回退），或以 root 重新运行。",
        file=sys.stderr,
    )
    return None


def _write_unit_file(path: Path, content: str, dry_run: bool) -> int:
    """写单元文件：root 直接写，非 root 走 sudo tee（stdin 传内容）。"""
    if dry_run:
        print(f"[DRY-RUN] 将写入单元文件 {path}：\n{content}")
        return 0
    try:
        if os.geteuid() == 0:
            path.write_text(content, encoding="utf-8")
            print(f"[OK] 已写入单元文件 {path}")
            return 0
        result = subprocess.run(
            ["sudo", "tee", str(path)],
            input=content,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=30,
        )
        if result.returncode != 0:
            print(f"[FAIL] 写入单元文件失败（退出码 {result.returncode}）。", file=sys.stderr)
            if result.stderr.strip():
                print(result.stderr.strip(), file=sys.stderr)
            return 1
        print(f"[OK] 已写入单元文件 {path}")
        return 0
    except subprocess.TimeoutExpired:
        print("[FAIL] 写入单元文件超时。", file=sys.stderr)
        return 1


def _install_systemd(args) -> int:
    unit_path = _service_unit_path()

    if args.uninstall:
        if not unit_path.is_file():
            print(f"[SKIP] 服务单元 {SERVICE_NAME} 不存在，无需删除。")
            return 0
        cmd = _with_sudo(["systemctl", "disable", "--now", SERVICE_NAME])
        if cmd is None:
            return 1
        rc = _run(cmd, "停止并禁用服务（disable --now）", dry_run=args.dry_run)
        if rc != 0:
            return rc
        if args.dry_run:
            print(f"[DRY-RUN] 将删除单元文件 {unit_path}")
            return 0
        cmd_rm = _with_sudo(["rm", "-f", str(unit_path)])
        if cmd_rm is None:
            return 1
        rc = _run(cmd_rm, "删除单元文件", dry_run=args.dry_run)
        if rc != 0:
            return rc
        cmd_rl = _with_sudo(["systemctl", "daemon-reload"])
        if cmd_rl is None:
            return 1
        return _run(cmd_rl, "重载 systemd 配置", dry_run=args.dry_run)

    if args.disable or args.enable:
        if not unit_path.is_file():
            print(f"[FAIL] 服务单元 {SERVICE_NAME} 不存在，请先运行默认（注册）模式。", file=sys.stderr)
            return 1
        verb = "disable" if args.disable else "enable"
        cmd = _with_sudo(["systemctl", verb, SERVICE_NAME])
        if cmd is None:
            return 1
        return _run(
            cmd,
            ("禁用开机自启（disable）" if args.disable else "启用开机自启（enable）"),
            dry_run=args.dry_run,
        )

    # 默认：写单元文件 + daemon-reload + enable --now（立即启动便于验证）
    if unit_path.is_file():
        print(f"[SKIP] 服务单元 {SERVICE_NAME} 已存在。")
    else:
        rc = _write_unit_file(unit_path, _service_unit_content(), args.dry_run)
        if rc != 0:
            return rc
    cmd_rl = _with_sudo(["systemctl", "daemon-reload"])
    if cmd_rl is None:
        return 1
    rc = _run(cmd_rl, "重载 systemd 配置", dry_run=args.dry_run)
    if rc != 0:
        return rc
    cmd_en = _with_sudo(["systemctl", "enable", "--now", SERVICE_NAME])
    if cmd_en is None:
        return 1
    rc = _run(cmd_en, "启用并启动服务（enable --now）", dry_run=args.dry_run)
    if rc != 0:
        return rc
    if args.dry_run:
        return 0
    cmd_st = _with_sudo(["systemctl", "status", SERVICE_NAME, "--no-pager"])
    return _run(cmd_st, "校验服务状态") if cmd_st else 1


# ---------------------------------------------------------------------------
# Linux/macOS 兜底：crontab @reboot（cron 守护进程开机即执行，无需登录、免 sudo）
# ---------------------------------------------------------------------------


def _read_crontab() -> list:
    """读取当前 crontab 内容（无任务时为空列表）。

    兼容不同实现：部分平台（BSD/macOS）把 "no crontab for <user>" 打到 stdout，
    另一些打到 stderr——因此两者都检查。
    """
    try:
        result = subprocess.run(
            ["crontab", "-l"], capture_output=True, text=True, errors="replace", timeout=30
        )
    except subprocess.TimeoutExpired:
        print("[FAIL] 读取 crontab 超时。", file=sys.stderr)
        raise RuntimeError("crontab -l 超时")
    output_text = ((result.stdout or "") + (result.stderr or "")).lower()
    if result.returncode != 0 and "no crontab" not in output_text:
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
    """生成（或按 enabled 转换）@reboot 自启行，尾部带唯一标记。

    @reboot 由 cron 守护进程在系统启动时执行，无需用户登录，满足物理开机自启。
    """
    root = _server_root()
    python = _venv_python()
    marker = _CRON_MARKER if enabled else _CRON_DISABLED_MARKER
    log_dir = Path.home() / ".mashiru-daily" / "todos"
    return f"@reboot cd {root} && {python} -m app.main >> {log_dir / 'autostart.log'} 2>&1 {marker}"


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
            print("[SKIP] crontab 中未找到自启行，无需删除。")
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
            print("[FAIL] crontab 中未找到自启行，请先运行默认（注册）模式。", file=sys.stderr)
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
    # 预创建日志目录，确保 @reboot 时 `>>` 重定向不因目录缺失而失败
    (Path.home() / ".mashiru-daily" / "todos").mkdir(parents=True, exist_ok=True)
    return _write_crontab(lines + [new_line])


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="注册/管理 MashiruDailyServer（拉取服务器）的物理开机自启（Windows: schtasks ONSTART；Linux/macOS: systemd 系统服务或 crontab）"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--uninstall", action="store_true", help="删除自启")
    group.add_argument("--disable", action="store_true", help="禁用自启（不删除）")
    group.add_argument("--enable", action="store_true", help="启用自启")
    parser.add_argument("--dry-run", action="store_true", help="只打印将执行的命令，不实际执行")
    args = parser.parse_args()

    if os.name == "nt":
        # Windows：schtasks ONSTART + /RU SYSTEM 需要管理员权限。
        # 不自动提权重启（runas 在受限/非交互会话下会静默失败且无感知），
        # 非管理员（且非演练）时打印手动操作指引并以退出码 2 退出。
        if not args.dry_run and not _is_admin_win():
            _print_manual_instructions(args)
            return EXIT_MANUAL_REQUIRED
        return _install_windows(args)

    # POSIX（Linux/macOS）：优先 systemd 系统服务（物理开机自启，需 root/sudo），
    # 无 systemd 时回退 crontab @reboot（cron 守护进程开机执行，免 sudo）。
    if _systemd_available():
        print(f"[INFO] 检测到 systemd，使用系统服务（{SERVICE_NAME}，物理开机自启）。")
        return _install_systemd(args)

    print("[INFO] 未检测到 systemd，回退 crontab @reboot 方式（开机即执行，无需登录）。")
    return _install_crontab(args)


if __name__ == "__main__":
    sys.exit(main())
