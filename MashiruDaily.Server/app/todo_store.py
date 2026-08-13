"""todo.json 与 todo-meta.json 的纯读取/初始化函数（无 HTTP 层，供 app/main.py 调用）。"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from app.config import get_settings


class TodoRecord(TypedDict):
    """todo.json 中的单条待办（PascalCase，与 C# 端 System.Text.Json 反序列化对齐）。"""

    Id: str
    Title: str
    IsCompleted: bool
    CreatedAt: str
    CompletedAt: str | None


class TodoMeta(TypedDict):
    """todo-meta.json 侧车结构：恰好 date / createdAt / count 三个字段，不多不少。"""

    date: str
    createdAt: str
    count: int


def _todo_json_path() -> Path:
    """返回数据目录下的 todo.json 路径。"""
    return get_settings().data_dir / "todo.json"


def _meta_json_path() -> Path:
    """返回数据目录下的 todo-meta.json 路径。"""
    return get_settings().data_dir / "todo-meta.json"


def _now_utc_iso() -> str:
    """当前 UTC 时间的 ISO8601 字符串，以 Z 结尾（如 2026-08-12T09:30:00.123456Z），
    与 C# 端 DateTimeOffset.TryParse(..., AssumeUniversal) 兼容。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_local() -> str:
    """今日本地日期，格式 yyyy-MM-dd。"""
    return datetime.now().strftime("%Y-%m-%d")


def load_todo_list() -> list[TodoRecord]:
    """读取 data/todo.json：文件缺失返回空列表；JSON 非法或顶层非数组抛 ValueError。"""
    path = _todo_json_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"todo.json 解析失败（{path}）：{exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"todo.json 顶层必须是 JSON 数组（{path}）")
    return data


def _read_meta(path: Path) -> TodoMeta:
    """读取已存在的侧车文件；JSON 非法或结构不符合 {date, createdAt, count} 抛 ValueError。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"todo-meta.json 解析失败（{path}）：{exc}") from exc
    # 形状校验：手改或旧版本写入的侧车若缺键，后续 current_meta 会抛 KeyError，
    # 与其余路径的 ValueError→500 JSON 不一致，这里统一为明确的 ValueError。
    if not isinstance(data, dict) or not {"date", "createdAt", "count"}.issubset(data):
        raise ValueError(f"todo-meta.json 结构不合法（{path}）：需要 date/createdAt/count 三键")
    return data


def _write_meta_atomic(path: Path, meta: TodoMeta) -> None:
    """原子写入侧车：先写同目录 .tmp 再 os.replace，避免落盘半截文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, path)


def load_or_init_meta() -> TodoMeta:
    """读取侧车；缺失时按当前数据初始化（date=今日、createdAt=当前 UTC、count=实时条数）
    并原子写入后返回。已存在的侧车绝不覆盖。"""
    path = _meta_json_path()
    if path.exists():
        return _read_meta(path)
    meta: TodoMeta = {
        "date": _today_local(),
        "createdAt": _now_utc_iso(),
        "count": len(load_todo_list()),
    }
    _write_meta_atomic(path, meta)
    return meta


def current_meta() -> TodoMeta:
    """返回当前元数据：date / createdAt 原样透传侧车，count 始终取 todo.json 实时长度；
    只读，绝不修改侧车。"""
    meta = load_or_init_meta()
    return {
        "date": meta["date"],
        "createdAt": meta["createdAt"],
        "count": len(load_todo_list()),
    }
