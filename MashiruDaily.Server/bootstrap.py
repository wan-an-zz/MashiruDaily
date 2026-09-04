"""MashiruDaily.Server 一键初始化程序（bootstrap.py，推荐入口）。

用系统 Python（纯标准库，无第三方依赖）按序串联六个幂等子脚本：
setup_server → register_hermes_plugin → configure_webhook → configure_cron →
install_autostart → 启动验证（/health 与 /api/todo/meta）。任一环节失败立即
终止（fail-fast），各子脚本幂等、可重复运行。Windows 非管理员下
install_autostart 不自动提权，以退出码 2 表示「需用户手动完成」——此时不中断
流程，改在末尾汇总提示用户按指引手动注册开机自启。

用法（在 MashiruDaily.Server 目录下用系统 Python 运行）：
    python bootstrap.py --secret <密钥>                    # 完整初始化
    python bootstrap.py --dry-run --secret <密钥>          # 演练：只打印命令

webhook 密钥经环境变量 MASHIRU_WEBHOOK_SECRET 注入子进程
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import install_autostart

# 服务器根目录（即本脚本所在目录）
SERVER_ROOT = Path(__file__).resolve().parent

# 启动验证：最长轮询时长与每次间隔（秒）
POLL_SECONDS = 30.0
POLL_INTERVAL = 0.5

# 拉取服务器默认端口（与 app/config.py 一致，可用环境变量 MASHIRU_PORT 覆盖）
DEFAULT_PORT = "8123"

# 程序运行过程中要求用户手动完成的操作提示；在 main 结束前统一再次输出
_ACTION_PROMPTS: list[str] = []


def venv_python(venv_dir: Path) -> Path:
    """返回虚拟环境内的解释器路径：Windows 为 Scripts/python.exe，其余平台为 bin/python。

    用字符串拼接而非 ``/`` 运算符，避免触发 pathlib 的 flavor 校验异常。
    """
    rel = "Scripts/python.exe" if os.name == "nt" else "bin/python"
    return Path(f"{venv_dir}/{rel}")


def _print_cmd(cmd: list[str]) -> None:
    """以 list2cmdline 形式打印将执行的命令。"""
    print(f"运行: {subprocess.list2cmdline(cmd)}")


def _remember_action_prompt(message: str) -> None:
    """打印一条要求用户手动操作的提示，并记录到程序末尾统一重放。"""
    _ACTION_PROMPTS.append(message)


def _print_action_prompts() -> None:
    """在程序最后再次输出所有要求用户手动操作的提示。"""
    if not _ACTION_PROMPTS:
        return
    print("\n" + "=" * 60)
    print("以下操作需要您手动完成，请勿遗漏：")
    for i, prompt in enumerate(_ACTION_PROMPTS, 1):
        print(f"{i}. {prompt}")
    print("=" * 60)


def _check_venv_python(venv_py: Path) -> bool:
    """预检虚拟环境解释器是否存在；缺失时打印提示并返回 False。"""
    if venv_py.is_file():
        return True
    _remember_action_prompt(
        f"[FAIL] 未找到虚拟环境解释器 {venv_py}。请先运行 setup_server.py 创建虚拟环境，或去掉 --skip-setup。"
    )
    return False


def _execute(
    cmd: list[str],
    *,
    env: dict | None = None,
    dry_run: bool = False,
    note: str | None = None,
) -> int:
    """执行子进程命令并返回退出码；dry-run 时只打印命令（标记 [DRY-RUN]）并返回 0。

    子进程输出直接继承本进程的标准输出/错误流（不捕获），保持子脚本原始输出样式。
    """
    _print_cmd(cmd)
    if note:
        print(note)
    if dry_run:
        print("[DRY-RUN] 演练模式，跳过实际执行。")
        return 0
    return subprocess.run(cmd, env=env, cwd=str(SERVER_ROOT)).returncode


def _health_ok(base_url: str) -> bool:
    """探测 /health；返回 True 表示服务器可访问且返回 200。"""
    try:
        with urllib.request.urlopen(f"{base_url}/health", timeout=5) as resp:
            return resp.getcode() == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def _spawn_server(venv_py: Path) -> subprocess.Popen:
    """拉起服务器子进程（python -m app.main），Windows 下隐藏控制台窗口。"""
    popen_kwargs = {
        "cwd": str(SERVER_ROOT), "env": dict(os.environ), "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE, "text": True, "errors": "replace",
    }
    if os.name == "nt":
        popen_kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
    return subprocess.Popen([str(venv_py), "-m", "app.main"], **popen_kwargs)


def _wait_ready(base_url: str, proc: subprocess.Popen) -> bool:
    """轮询等待服务器就绪（最多 POLL_SECONDS 秒）：进程退出即快速失败。"""
    for _ in range(int(POLL_SECONDS / POLL_INTERVAL)):
        time.sleep(POLL_INTERVAL)
        if proc.poll() is not None:
            stderr_stream = getattr(proc, "stderr", None)
            if stderr_stream is not None:
                try:
                    tail = stderr_stream.read()
                except (OSError, ValueError):
                    tail = ""
                if tail.strip():
                    print(tail.strip(), file=sys.stderr)
            print("[FAIL] 服务器进程异常退出，启动验证失败。", file=sys.stderr)
            return False
        if _health_ok(base_url):
            return True
    print("[FAIL] 等待服务器就绪超时（30 秒），/health 始终未返回 200。", file=sys.stderr)
    return False


def _terminate_proc(proc: subprocess.Popen) -> None:
    """终止服务器子进程：Windows 用 taskkill 整树终止，POSIX 用 terminate→kill。"""
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            errors="replace",
        )
    else:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except (OSError, ValueError, subprocess.TimeoutExpired):
            # 等待被信号打断或进程未及时退出：直接强杀兜底，不再复查
            proc.kill()
            return
        if proc.poll() is None:
            proc.kill()


def _verify(venv_py: Path) -> int:
    """启动服务器并验证 /health 与 /api/todo/meta；返回退出码（0 成功，1 失败）。"""
    host = os.environ.get("MASHIRU_HOST") or "127.0.0.1"
    if host == "0.0.0.0":
        host = "127.0.0.1"
    port = os.environ.get("MASHIRU_PORT") or DEFAULT_PORT
    base_url = f"http://{host}:{port}"

    proc = None
    try:
        # Windows：若服务器已在运行则直接复用，避免重复拉起；POSIX：始终拉起独立实例验证
        if os.name == "nt" and _health_ok(base_url):
            print("[OK] 检测到服务器已在运行，直接复用现有实例。")
        else:
            proc = _spawn_server(venv_py)
            if not _wait_ready(base_url, proc):
                return 1

        # 校验元数据：响应必须为 dict 且含非空 created_at
        try:
            with urllib.request.urlopen(f"{base_url}/api/todo/meta", timeout=5) as resp:
                meta = json.loads(resp.read())
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            print("[FAIL] /api/todo/meta 请求失败或返回非法 JSON。", file=sys.stderr)
            return 1
        if not isinstance(meta, dict) or not meta.get("created_at"):
            print("[FAIL] /api/todo/meta 响应非法：缺少非空 created_at。", file=sys.stderr)
            return 1

        print("[OK] 启动验证通过：/health 200，/api/todo/meta 正常。")
        return 0
    finally:
        if proc is not None:
            _terminate_proc(proc)


def _main(argv: list[str] | None = None) -> int:
    """解析参数并按序执行六个步骤；返回退出码（不抛出 SystemExit）。"""
    parser = argparse.ArgumentParser(
        description="MashiruDaily.Server 一键初始化：按序串联六个幂等子脚本并做启动验证"
    )
    parser.add_argument("--venv", default=".venv", help="虚拟环境目录名（默认 .venv）")
    parser.add_argument(
        "--secret",
        default=None,
        help="webhook 密钥（也可用环境变量 MASHIRU_WEBHOOK_SECRET 提供）",
    )
    parser.add_argument("--skip-setup", action="store_true", help="跳过步骤 1：setup_server.py")
    parser.add_argument("--skip-skills", action="store_true", help="跳过步骤 2：register_hermes_plugin.py")
    parser.add_argument("--skip-webhook", action="store_true", help="跳过步骤 3：configure_webhook.py")
    parser.add_argument("--skip-cron", action="store_true", help="跳过步骤 4：configure_cron.py")
    parser.add_argument("--skip-autostart", action="store_true", help="跳过步骤 5：install_autostart.py")
    parser.add_argument("--no-verify", action="store_true", help="跳过步骤 6：启动验证")
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="透传 configure_webhook：不自动重启 Hermes 网关",
    )
    parser.add_argument(
        "--schedule",
        default="0 9 * * *",
        help="透传 configure_cron 的 cron 表达式（默认 0 9 * * *）",
    )
    parser.add_argument("--dry-run", action="store_true", help="演练：只打印将执行的命令，不实际执行")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    venv_py = venv_python(SERVER_ROOT / args.venv)

    # 步骤 1/6：setup_server.py（用系统 Python 运行，先于虚拟环境创建）
    print("\n[1/6] 初始化服务器：创建虚拟环境、安装依赖、初始化数据（setup_server.py）")
    if args.skip_setup:
        print("[SKIP] 已跳过（--skip-setup）。")
    else:
        rc = _execute(
            [sys.executable, "setup_server.py", "--venv", args.venv],
            dry_run=args.dry_run,
        )
        if rc != 0:
            print(f"[FAIL] setup_server.py 失败（退出码 {rc}）。", file=sys.stderr)
            return rc
        print("[OK] setup_server.py 完成。")

    # 步骤 2/6：register_hermes_plugin.py（用 venv python 运行）
    print("\n[2/6] 注册 Hermes 插件与 skills（register_hermes_plugin.py）")
    if args.skip_skills:
        print("[SKIP] 已跳过（--skip-skills）。")
    elif not _check_venv_python(venv_py):
        return 1
    else:
        rc = _execute([str(venv_py), "register_hermes_plugin.py"], dry_run=args.dry_run)
        if rc != 0:
            print(f"[FAIL] register_hermes_plugin.py 失败（退出码 {rc}）。", file=sys.stderr)
            return rc
        print("[OK] register_hermes_plugin.py 完成。")

    # 步骤 3/6：configure_webhook.py（密钥经环境变量注入，绝不进命令行）
    print("\n[3/6] 配置 Hermes webhook 平台与 todo-sync 路由（configure_webhook.py）")
    if args.skip_webhook:
        print("[SKIP] 已跳过（--skip-webhook）。")
    elif not _check_venv_python(venv_py):
        return 1
    else:
        secret = args.secret or os.environ.get("MASHIRU_WEBHOOK_SECRET")
        if not secret:
            _remember_action_prompt(
                "[FAIL] 缺少 webhook 密钥：请通过 --secret <密钥> 或环境变量 MASHIRU_WEBHOOK_SECRET 提供。"
            )
            return 1
        base_env = dict(os.environ)
        if args.secret:
            base_env["MASHIRU_WEBHOOK_SECRET"] = args.secret
        webhook_cmd = [str(venv_py), "configure_webhook.py"]
        if args.no_restart:
            webhook_cmd.append("--no-restart")
        rc = _execute(webhook_cmd, env=base_env, dry_run=args.dry_run,
                      note="（secret 经环境变量 MASHIRU_WEBHOOK_SECRET 传入，不显示）")
        if rc == 1:
            print(f"[FAIL] configure_webhook.py 失败（退出码 {rc}）。", file=sys.stderr)
            return rc
        if rc == 2:
            _remember_action_prompt("[提示] Hermes 拒绝在 root 下重启网关，webhook 配置已写入 config.yaml，\n将在 Hermes 下次重启时生效。本次未执行重启；可手动重启或等待下次重启。\n建议运行`sudo systemctl restart hermes-gateway.service完成重启`。")
        elif rc == 3:
            _remember_action_prompt("[提示] Hermes 拒绝在 root 下重启网关，webhook 配置已写入 config.yaml，\n将在 Hermes 下次重启时生效。本次未执行重启；可手动重启或等待下次重启。\n建议在Hermes所属用户下运行`hermes gateway restart`或`sudo systemctl restart hermes-gateway.service完成重启`")
        elif rc != 0:
            print(f"[FAIL] configure_webhook.py 失败（退出码 {rc}）。", file=sys.stderr)
            return rc
        print("[OK] configure_webhook.py 完成。")
        
        if args.no_restart and not args.dry_run:
            _remember_action_prompt("[提示] webhook 配置已写入但未自动重启网关，请手动执行：hermes gateway restart")

    # 步骤 4/6：configure_cron.py（透传 --schedule）
    print("\n[4/6] 创建每日 Hermes cron 任务 mashiru-daily（configure_cron.py）")
    if args.skip_cron:
        print("[SKIP] 已跳过（--skip-cron）。")
    elif not _check_venv_python(venv_py):
        return 1
    else:
        rc = _execute(
            [str(venv_py), "configure_cron.py", "--schedule", args.schedule],
            dry_run=args.dry_run,
        )
        if rc != 0:
            print(f"[FAIL] configure_cron.py 失败（退出码 {rc}）。", file=sys.stderr)
            return rc
        print("[OK] configure_cron.py 完成。")

    # 步骤 5/6：install_autostart.py（dry-run 时以 --dry-run 真实执行，属只读演练）
    print("\n[5/6] 注册物理开机自启（install_autostart.py）")
    if args.skip_autostart:
        print("[SKIP] 已跳过（--skip-autostart）。")
    elif not _check_venv_python(venv_py):
        return 1
    else:
        if args.venv != ".venv":
            _remember_action_prompt("[WARN] install_autostart 硬编码 .venv，自定义虚拟环境名不会生效。")
        if args.dry_run:
            autostart_cmd = [str(venv_py), "install_autostart.py", "--dry-run"]
        else:
            autostart_cmd = [str(venv_py), "install_autostart.py"]
        rc = _execute(autostart_cmd)
        if rc == install_autostart.EXIT_MANUAL_REQUIRED:
            rerun_cmd = subprocess.list2cmdline(
                [str(venv_py), str(SERVER_ROOT / "install_autostart.py")]
            )
            _remember_action_prompt(
                "[提示] Windows 开机自启未注册：需要管理员权限。"
                f"请以管理员身份打开终端后执行：{rerun_cmd}"
            )
            print("[待手动] 开机自启注册需手动完成（见上方指引，末尾会再次提示）。")
        elif rc != 0:
            print(f"[FAIL] install_autostart.py 失败（退出码 {rc}）。", file=sys.stderr)
            return rc
        else:
            print("[OK] install_autostart.py 完成。")
            if os.name == "nt" and not args.dry_run:
                _remember_action_prompt(
                    "[提示] Windows 开机自启任务已就绪（ONSTART）：将在下次开机时自动启动服务，"
                    "当前不会立即运行。若需立即启动，请执行："
                    f"schtasks /Run /TN {install_autostart.TASK_NAME}"
                )

    # 步骤 6/6：启动验证
    print("\n[6/6] 启动验证：检查 /health 与 /api/todo/meta")
    if args.no_verify:
        print("[SKIP] 已跳过（--no-verify）。")
        return 0
    if args.dry_run:
        print(f"运行: {str(venv_py)} -m app.main（后台拉起，轮询 /health 与 /api/todo/meta 后自动关闭）")
        print("[DRY-RUN] 演练模式，跳过实际启动与探测。")
        return 0
    return _verify(venv_py)


def main(argv: list[str] | None = None) -> int:
    """入口：执行初始化，并在最后重放所有要求用户手动完成的提示。"""
    _ACTION_PROMPTS.clear()
    try:
        return _main(argv)
    finally:
        _print_action_prompts()
        _ACTION_PROMPTS.clear()


if __name__ == "__main__":
    sys.exit(main())
