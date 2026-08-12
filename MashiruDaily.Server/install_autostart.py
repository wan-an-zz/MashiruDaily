"""注册/管理 MashiruDailyServer（拉取服务器）的 Windows 登录自启计划任务（幂等）。

- 默认注册：schtasks /Create /TN MashiruDailyServer /TR "<.venv\\Scripts\\pythonw.exe> -m app.main" /SC ONLOGON /F
  （使用 pythonw.exe，避免弹出控制台窗口）；
- --uninstall：删除该任务；--disable / --enable：启用/禁用该任务（不删除）；
- 创建后自动执行 schtasks /Query 校验。

用法：
    .venv\\Scripts\\python.exe install_autostart.py            # 注册登录自启
    .venv\\Scripts\\python.exe install_autostart.py --disable  # 临时禁用
    .venv\\Scripts\\python.exe install_autostart.py --enable   # 重新启用
    .venv\\Scripts\\python.exe install_autostart.py --uninstall
"""

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

TASK_NAME = "MashiruDailyServer"


def _task_exists() -> bool:
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


def _run_schtasks(args_list, action_desc: str, timeout: int = 30) -> int:
    """执行 schtasks 命令并打印结果，返回退出码。"""
    print(f"运行: {subprocess.list2cmdline(args_list)}")
    try:
        result = subprocess.run(
            args_list,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="注册/管理 MashiruDailyServer（拉取服务器）的 Windows 登录自启计划任务（幂等）"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--uninstall", action="store_true", help="删除自启任务")
    group.add_argument("--disable", action="store_true", help="禁用自启任务（不删除）")
    group.add_argument("--enable", action="store_true", help="启用自启任务")
    args = parser.parse_args()

    if os.name != "nt":
        print("错误：本脚本仅支持 Windows（依赖 schtasks 注册登录自启）。", file=sys.stderr)
        return 1
    if shutil.which("schtasks") is None:
        print("错误：未找到 schtasks 命令。", file=sys.stderr)
        return 1

    # --uninstall：先确认存在，避免重复删除报错（幂等）
    if args.uninstall:
        if not _task_exists():
            print(f"[SKIP] 计划任务 {TASK_NAME} 不存在，无需删除。")
            return 0
        return _run_schtasks(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], "删除自启任务")

    # --disable / --enable
    if args.disable or args.enable:
        if not _task_exists():
            print(f"[FAIL] 计划任务 {TASK_NAME} 不存在，请先运行默认（注册）模式。", file=sys.stderr)
            return 1
        flag = "/DISABLE" if args.disable else "/ENABLE"
        return _run_schtasks(
            ["schtasks", "/Change", "/TN", TASK_NAME, flag],
            "禁用自启任务" if args.disable else "启用自启任务",
        )

    # 默认：注册登录自启
    server_root = Path(__file__).resolve().parent
    pythonw = server_root / ".venv" / "Scripts" / "pythonw.exe"
    if not pythonw.is_file():
        print(f"[WARN] 未找到 {pythonw}，请先运行 setup_server.py 创建虚拟环境，否则登录自启将无法启动服务。")
    task_run = f'"{pythonw}" -m app.main'
    print(f"[INFO] 计划任务命令：{task_run}")

    rc = _run_schtasks(
        ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", task_run, "/SC", "ONLOGON", "/F"],
        "注册登录自启任务",
    )
    if rc != 0:
        return rc

    # 创建后校验
    return _run_schtasks(["schtasks", "/Query", "/TN", TASK_NAME, "/FO", "LIST"], "校验任务状态")


if __name__ == "__main__":
    sys.exit(main())
