"""Hermes 插件工具实现：读写 MashiruDaily.Server 的 data/todo.json 与 data/todo-meta.json。

设计约束：
- 只依赖 Python 标准库，便于 Hermes 进程直接加载；
- 所有 handler 都返回 JSON 字符串，错误也以 JSON 返回，绝不向上抛异常；
- 落盘沿用原子写（tmp + os.replace），避免半截文件；
- 与 app/todo_store.py 的语义保持一致：todo-meta.json 的 createdAt 只能由
  todo_meta_stamp 刷新。
- Id/CreatedAt/CompletedAt 统一由程序生成或维护，Hermes Agent 不自行编造；
  只有更新/完成已有条目时可传入已存在的 Id 用于定位。
"""

import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path


def _server_root() -> Path:
    """返回 MashiruDaily.Server 根目录（hermes_plugin/mashiru_daily 的上三级）。"""
    return Path(__file__).resolve().parent.parent.parent


def _data_dir() -> Path:
    """返回数据目录：优先环境变量 MASHIRU_DATA_DIR，否则 Server/data。"""
    env = os.environ.get("MASHIRU_DATA_DIR")
    if env:
        return Path(env)
    return _server_root() / "data"


def _todo_path() -> Path:
    """返回 data/todo.json 路径。"""
    return _data_dir() / "todo.json"


def _meta_path() -> Path:
    """返回 data/todo-meta.json 路径。"""
    return _data_dir() / "todo-meta.json"


def _now_utc_iso() -> str:
    """当前 UTC 时间的 ISO8601 字符串，以 Z 结尾（与 C# 端 AssumeUniversal 解析兼容）。"""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _today_local() -> str:
    """今日本地日期，格式 yyyy-MM-dd。"""
    return datetime.now().strftime("%Y-%m-%d")


def _atomic_write_json(path: Path, data) -> None:
    """原子写入 JSON 文件：先写 .tmp 再 os.replace。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(tmp_path, path)


def _load_todo_list() -> list:
    """读取 data/todo.json；文件缺失返回空列表，非法 JSON 或顶层非数组抛 ValueError。"""
    path = _todo_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"todo.json 解析失败（{path}）：{exc}") from exc
    if not isinstance(data, list):
        raise ValueError(f"todo.json 顶层必须是 JSON 数组（{path}）")
    return data


def _new_item(title: str) -> dict:
    """根据标题生成一条完整待办：Id/CreatedAt 由程序生成，CompletedAt 初始为 null。"""
    return {
        "Id": str(uuid.uuid4()),
        "Title": title,
        "IsCompleted": False,
        "CreatedAt": _now_utc_iso(),
        "CompletedAt": None,
    }


def _archive_todo_before_overwrite() -> Path | None:
    """覆盖前将现有 todo.json 存档到 data/backups/todo-<时间戳>-<随机后缀>.json；无文件时返回 None。"""
    src = _todo_path()
    if not src.exists():
        return None
    backup_dir = _data_dir() / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
    backup_path = backup_dir / f"todo-{timestamp}-{uuid.uuid4().hex[:8]}.json"
    shutil.copy2(src, backup_path)
    return backup_path


def _load_or_init_meta() -> dict:
    """读取侧车；缺失时按当前数据初始化并原子写入后返回。"""
    path = _meta_path()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"todo-meta.json 解析失败（{path}）：{exc}") from exc
        if not isinstance(data, dict) or not {"date", "createdAt", "count"}.issubset(data):
            raise ValueError(f"todo-meta.json 结构不合法（{path}）：需要 date/createdAt/count 三键")
        return data
    meta = {
        "date": _today_local(),
        "createdAt": _now_utc_iso(),
        "count": len(_load_todo_list()),
    }
    _atomic_write_json(path, meta)
    return meta


def _current_meta() -> dict:
    """返回当前元数据：date/createdAt 透传侧车，count 实时取自 todo.json。"""
    meta = _load_or_init_meta()
    return {
        "date": meta["date"],
        "createdAt": meta["createdAt"],
        "count": len(_load_todo_list()),
    }


def _stamp_meta() -> dict:
    """刷新 todo-meta.json：date=今日、createdAt=当前 UTC、count=实时条数。"""
    meta = {
        "date": _today_local(),
        "createdAt": _now_utc_iso(),
        "count": len(_load_todo_list()),
    }
    _atomic_write_json(_meta_path(), meta)
    return meta


def _ok(data) -> str:
    """将成功结果序列化为 JSON 字符串。"""
    return json.dumps(data, ensure_ascii=False)


def _err(message) -> str:
    """将错误信息序列化为 JSON 字符串（Hermes handler 不抛异常）。"""
    return json.dumps({"success": False, "error": str(message)}, ensure_ascii=False)


def todo_list(args: dict, **kwargs) -> str:
    """读取 data/todo.json 全量列表。"""
    try:
        return _ok({"success": True, "items": _load_todo_list()})
    except Exception as exc:
        return _err(exc)


def todo_get(args: dict, **kwargs) -> str:
    """按 Id 读取单条待办。"""
    try:
        item_id = str(args.get("id") or "")
        if not item_id:
            return _err("缺少参数 id")
        for item in _load_todo_list():
            if item.get("Id") == item_id:
                return _ok({"success": True, "item": item})
        return _ok({"success": False, "found": False, "id": item_id})
    except Exception as exc:
        return _err(exc)


def todo_save(args: dict, **kwargs) -> str:
    """整体覆盖写入 data/todo.json：覆盖前先将旧文件存档到 data/backups，再执行写入。"""
    try:
        titles = args.get("items")
        if titles is None:
            titles = args.get("titles")
        if not isinstance(titles, list):
            return _err("参数 items 必须是数组")
        items = []
        for title in titles:
            if not isinstance(title, str) or not title.strip():
                return _err("Title 必须是非空字符串")
            items.append(_new_item(title))
        _archive_todo_before_overwrite()
        _atomic_write_json(_todo_path(), items)
        return _ok({"success": True, "count": len(items)})
    except Exception as exc:
        return _err(exc)


def todo_upsert(args: dict, **kwargs) -> str:
    """按 Id 更新已有待办标题；未传 Id 或 Id 为空时新增待办。"""
    try:
        title = args.get("title")
        if not isinstance(title, str) or not title.strip():
            return _err("参数 title 必须是非空字符串")
        item_id = str(args.get("id") or "").strip()
        items = _load_todo_list()
        if item_id:
            for index, existing in enumerate(items):
                if existing.get("Id") == item_id:
                    items[index] = {**existing, "Title": title}
                    _atomic_write_json(_todo_path(), items)
                    return _ok({"success": True, "created": False, "item": items[index], "count": len(items)})
            return _ok({"success": False, "found": False, "id": item_id})
        item = _new_item(title)
        items.append(item)
        _atomic_write_json(_todo_path(), items)
        return _ok({"success": True, "created": True, "item": item, "count": len(items)})
    except Exception as exc:
        return _err(exc)


def todo_completed(args: dict, **kwargs) -> str:
    """按 Id 修改待办完成状态；CompletedAt 由程序生成或清空。"""
    try:
        item_id = str(args.get("id") or "")
        if not item_id:
            return _err("缺少参数 id")
        completed = args.get("completed")
        if not isinstance(completed, bool):
            return _err("参数 completed 必须是布尔值")
        items = _load_todo_list()
        for item in items:
            if item.get("Id") == item_id:
                item["IsCompleted"] = completed
                item["CompletedAt"] = _now_utc_iso() if completed else None
                _atomic_write_json(_todo_path(), items)
                return _ok({"success": True, "item": item, "count": len(items)})
        return _ok({"success": False, "found": False, "id": item_id})
    except Exception as exc:
        return _err(exc)


def todo_delete(args: dict, **kwargs) -> str:
    """按 Id 删除待办。"""
    try:
        item_id = str(args.get("id") or "")
        if not item_id:
            return _err("缺少参数 id")
        items = _load_todo_list()
        new_items = [item for item in items if item.get("Id") != item_id]
        if len(new_items) == len(items):
            return _ok({"success": False, "deleted": False, "id": item_id})
        _atomic_write_json(_todo_path(), new_items)
        return _ok({"success": True, "deleted": True, "id": item_id, "count": len(new_items)})
    except Exception as exc:
        return _err(exc)


def todo_meta_get(args: dict, **kwargs) -> str:
    """读取 data/todo-meta.json 元数据（缺失时初始化）。"""
    try:
        return _ok({"success": True, "meta": _current_meta()})
    except Exception as exc:
        return _err(exc)


def todo_meta_stamp(args: dict, **kwargs) -> str:
    """刷新 data/todo-meta.json 的 createdAt 与 count。"""
    try:
        return _ok({"success": True, "meta": _stamp_meta()})
    except Exception as exc:
        return _err(exc)
