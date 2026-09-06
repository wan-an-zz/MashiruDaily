"""创建 Hermes 每日定时任务 mashiru-daily（幂等）。

- 先执行 `hermes cron list` 检查：任务已存在则打印“已存在，跳过”并以 0 退出；
- 否则执行 `hermes cron create "<schedule>" "<prompt>" --name mashiru-daily --workdir <Server目录> --skill todo-assigning`；
- 创建成功后再次打印 `hermes cron list` 确认。

用法：
    .venv\\Scripts\\python.exe configure_cron.py
    .venv\\Scripts\\python.exe configure_cron.py --schedule "0 9 * * *"
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

import _config  # 本目录共享的 Hermes 配置工具

# 默认 cron 表达式：每日 06:00
DEFAULT_SCHEDULE = "0 6 * * *"


def _run_cmd(cmd, timeout):
    """运行 hermes 子命令；超时（或异常）时给出清晰错误并以退出码 1 结束。"""
    try:
        return _config.run_command(cmd, timeout=timeout)
    except TimeoutError:
        print(f"错误：命令超时（>{timeout}s）：{subprocess.list2cmdline(cmd)}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="创建每日的 Hermes 定时任务 mashiru-daily（幂等，已存在则跳过）"
    )
    parser.add_argument("--name", default="mashiru-daily", help="任务名称（默认 mashiru-daily）")
    parser.add_argument("--schedule", default=DEFAULT_SCHEDULE, help="cron 表达式（默认每日 09:00：0 9 * * *）")
    parser.add_argument("--workdir", default=None, help="任务工作目录（默认本 Server 目录）")
    args = parser.parse_args()

    # 定位 hermes 可执行文件
    hermes = _config.find_hermes_exe()
    if hermes is None:
        print("错误：找不到 hermes 可执行文件。", file=sys.stderr)
        print("请确认已安装 Hermes Agent（HERMES_HOME/hermes-agent/venv 下，Windows 为 Scripts/hermes.exe，Linux/macOS 为 bin/hermes），", file=sys.stderr)
        print("或将其加入 PATH，或设置 HERMES_HOME 环境变量。", file=sys.stderr)
        return 1

    # 步骤 1：查询现有任务（幂等检查）
    print(f"运行: {subprocess.list2cmdline([hermes, 'cron', 'list'])}")
    result = _run_cmd([hermes, "cron", "list"], timeout=60)
    if result.returncode != 0:
        print("错误：hermes cron list 执行失败。", file=sys.stderr)
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return 1
    list_output = (result.stdout or "") + (result.stderr or "")
    if list_output.strip():
        print(list_output.strip())
    # 幂等检查：要求任务名前后是空白或行界（而非任意非单词字符），
    # 否则 mashiru-daily-backup 之类同名前缀任务会被误判为已存在。
    name_pattern = re.compile(rf"(^|\s){re.escape(args.name)}(\s|$)")
    if any(name_pattern.search(line) for line in list_output.splitlines()):
        print(f"[SKIP] cron 任务 {args.name} 已存在，跳过。")
        return 0

    # 构造提示词
    prompt = (
        "你是一个根据**已制定的计划**为用户分配当日任务的**任务分配者**。遵循todo-assigning skill的步骤，修改todo.json，为用户分配任务"
    )

    # 步骤 2：创建任务
    create_cmd = [
        hermes, "cron", "create", args.schedule, prompt,
        "--name", args.name, "--skill", "todo-assigning",
    ]
    print(f"\n运行: {subprocess.list2cmdline(create_cmd)}")
    result = _run_cmd(create_cmd, timeout=120)
    if result.returncode != 0:
        print("错误：hermes cron create 执行失败。", file=sys.stderr)
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return 1
    if result.stdout.strip():
        print(result.stdout.strip())
    print(f"[OK] cron 任务 {args.name} 创建成功。")

    # 步骤 3：再次列出确认
    print("\n创建后的 hermes cron list 输出：")
    result = _run_cmd([hermes, "cron", "list"], timeout=60)
    if result.returncode != 0:
        print("警告：hermes cron list 确认查询失败。", file=sys.stderr)
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
    else:
        print((result.stdout or "").strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
