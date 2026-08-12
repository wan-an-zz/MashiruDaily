#!/usr/bin/env python3
"""每日戳记脚本：重写 todo-meta.json 的 createdAt。

这是唯一允许改变 createdAt 的代码路径——Hermes 每日 cron 结束时、以及
setup_server.py 均通过子进程调用本脚本；Webhook 驱动的 todo.json 修改
绝不会触碰 createdAt（否则客户端会在每次 webhook 后误判需要重新拉取）。
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# 以脚本方式运行时 sys.path[0] 是 tools/ 目录，需把 Server 根目录插入
# sys.path，才能 import app 包（无论从哪个工作目录调用都成立）。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.todo_store import TodoMeta, load_todo_list  # noqa: E402


def _now_utc_iso() -> str:
    """当前 UTC 时间的 ISO8601 字符串，以 Z 结尾（与 C# 端 AssumeUniversal 解析兼容）。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_local() -> str:
    """今日本地日期，格式 yyyy-MM-dd。"""
    return datetime.now().strftime("%Y-%m-%d")


def main() -> int:
    """计算新的 date / createdAt / count 并原子重写 todo-meta.json，打印确认信息。"""
    data_dir = get_settings().data_dir
    data_dir.mkdir(parents=True, exist_ok=True)

    meta: TodoMeta = {
        "date": _today_local(),
        "createdAt": _now_utc_iso(),
        "count": len(load_todo_list()),
    }

    path = data_dir / "todo-meta.json"
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, path)

    print(
        f"todo-meta 已戳记: date={meta['date']} "
        f"createdAt={meta['createdAt']} count={meta['count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
