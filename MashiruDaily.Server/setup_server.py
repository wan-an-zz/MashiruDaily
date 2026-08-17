"""MashiruDaily.Server 一次性初始化脚本（幂等，可重复运行）。

用系统 Python（无需任何第三方依赖）执行：
1. 创建虚拟环境 .venv（已存在则跳过）；
2. 用 .venv 的 pip 安装 requirements.txt；
3. 创建 data/ 数据目录；
4. 调用 hermes_plugin 的 todo_meta_stamp 生成/刷新初始 sidecar（每次显式运行都会刷新 createdAt，属预期行为）。

仅依赖标准库：venv / subprocess / pathlib / argparse / os / sys / json。
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def run(cmd, timeout, env=None):
    """运行子进程并返回 CompletedProcess（文本输出、非法字节容错）。"""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
        env=env,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="初始化 MashiruDaily.Server：创建虚拟环境、安装依赖、初始化数据目录与元数据（幂等）"
    )
    parser.add_argument("--venv", default=".venv", help="虚拟环境目录名（默认 .venv）")
    args = parser.parse_args()

    server_root = Path(__file__).resolve().parent
    venv_dir = server_root / args.venv
    data_dir = server_root / "data"
    requirements = server_root / "requirements.txt"

    # venv 内 python 的位置：Windows 为 Scripts\\python.exe，其它平台为 bin/python
    venv_python = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    if sys.prefix != sys.base_prefix:
        print("[WARN] 检测到当前运行在虚拟环境中，建议改用系统 Python 运行本脚本，以免产生嵌套虚拟环境。")

    # 步骤 1：创建虚拟环境
    print("\n[1/4] 创建虚拟环境 .venv")
    if venv_python.is_file():
        print(f"[SKIP] 虚拟环境已存在（{venv_dir}），跳过创建。")
    else:
        print(f"运行: {sys.executable} -m venv {venv_dir}")
        try:
            result = run([sys.executable, "-m", "venv", str(venv_dir)], timeout=300)
        except subprocess.TimeoutExpired:
            print("[FAIL] 创建虚拟环境超时。", file=sys.stderr)
            return 1
        if result.returncode != 0 or not venv_python.is_file():
            print("[FAIL] 虚拟环境创建失败。", file=sys.stderr)
            print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
            return 1
        print("[OK] 虚拟环境创建完成。")

    # 步骤 2：安装依赖
    print("\n[2/4] 安装依赖 requirements.txt")
    if not requirements.is_file():
        print(f"[WARN] 未找到 {requirements}，跳过依赖安装。")
    else:
        print(f"运行: {venv_python} -m pip install -r {requirements}")
        try:
            result = run([str(venv_python), "-m", "pip", "install", "-r", str(requirements)], timeout=600)
        except subprocess.TimeoutExpired:
            print("[FAIL] 依赖安装超时。", file=sys.stderr)
            return 1
        if result.returncode != 0:
            print("[FAIL] 依赖安装失败。", file=sys.stderr)
            print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
            return 1
        print("[OK] 依赖安装完成。")

    # 步骤 3：创建数据目录
    print("\n[3/4] 创建 data/ 数据目录")
    data_dir.mkdir(parents=True, exist_ok=True)
    print(f"[OK] 数据目录就绪：{data_dir}")

    # 步骤 4：盖章初始元数据（sidecar）
    print("\n[4/4] 调用 todo_meta_stamp 生成初始 sidecar")
    sys.path.insert(0, str(server_root))
    os.environ["MASHIRU_DATA_DIR"] = str(data_dir)
    try:
        from hermes_plugin.mashiru_daily.tools import todo_meta_stamp

        stamp_result = json.loads(todo_meta_stamp({}))
    except Exception as exc:
        print(f"[FAIL] 盖章工具执行失败：{exc}", file=sys.stderr)
        return 1
    if not stamp_result.get("success"):
        print(f"[FAIL] 盖章工具执行失败：{stamp_result.get('error')}", file=sys.stderr)
        return 1
    print(f"[OK] 初始 sidecar 已生成（{stamp_result['meta']}）。")

    print("\n[完成] 初始化成功。可继续运行 register_hermes_plugin.py / configure_webhook.py / configure_cron.py / install_autostart.py。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
