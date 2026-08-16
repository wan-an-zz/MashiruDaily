"""hermes_plugin 工具的离线契约测试。

不依赖 FastAPI / Hermes 进程，只验证插件内的 todo_* handler：
- todo.json / todo-meta.json 的读写均通过 handler 返回的 JSON 字符串；
- 临时数据目录由 MASHIRU_DATA_DIR 注入，测试后自动还原。
"""

import json
import sys
from datetime import datetime
from pathlib import Path

import pytest

# 保证可以 import hermes_plugin（Server 根目录）
SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from hermes_plugin.mashiru_daily import tools  # noqa: E402


def _invoke(handler, **kwargs) -> dict:
    """调用 handler 并解析返回的 JSON 字符串。"""
    return json.loads(handler(kwargs))


def _item(todo_id: str, title: str = "测试待办") -> dict:
    """构造一条符合契约的 PascalCase 待办记录。"""
    return {
        "Id": todo_id,
        "Title": title,
        "IsCompleted": False,
        "CreatedAt": "2026-08-12T08:00:00+08:00",
        "CompletedAt": None,
    }


@pytest.fixture()
def plugin_data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """让插件工具指向临时数据目录。"""
    monkeypatch.setenv("MASHIRU_DATA_DIR", str(tmp_path))
    return tmp_path


def test_todo_list_returns_empty_without_file(plugin_data_dir) -> None:
    """todo.json 缺失时 todo_list 返回空数组。"""
    result = _invoke(tools.todo_list)
    assert result["success"] is True
    assert result["items"] == []


def test_todo_save_and_list_roundtrip(plugin_data_dir) -> None:
    """todo_save 写入后 todo_list 能逐字读回。"""
    items = [_item("1", "买牛奶"), _item("2", "写周报")]
    saved = _invoke(tools.todo_save, items=items)
    assert saved["success"] is True
    assert saved["count"] == 2

    listed = _invoke(tools.todo_list)
    assert listed["items"] == items
    for item in listed["items"]:
        assert set(item.keys()) == {"Id", "Title", "IsCompleted", "CreatedAt", "CompletedAt"}
        assert "HasSynced" not in item


def test_todo_upsert_adds_and_updates(plugin_data_dir) -> None:
    """todo_upsert：新 Id 新增，已有 Id 更新。"""
    first = _invoke(tools.todo_upsert, item=_item("1", "买菜"))
    assert first["success"] is True
    assert first["created"] is True
    assert first["count"] == 1

    updated_item = {**_item("1", "买菜并记账"), "IsCompleted": True, "CompletedAt": "2026-08-12T09:00:00+08:00"}
    second = _invoke(tools.todo_upsert, item=updated_item)
    assert second["success"] is True
    assert second["created"] is False
    assert second["count"] == 1

    listed = _invoke(tools.todo_list)
    assert listed["items"][0]["Title"] == "买菜并记账"
    assert listed["items"][0]["IsCompleted"] is True


def test_todo_delete_removes_by_id(plugin_data_dir) -> None:
    """todo_delete 按 Id 删除；不存在时返回 success=false 且 deleted=false。"""
    _invoke(tools.todo_save, items=[_item("1", "买牛奶"), _item("2", "写周报")])

    deleted = _invoke(tools.todo_delete, id="1")
    assert deleted["success"] is True
    assert deleted["deleted"] is True
    assert deleted["count"] == 1

    missing = _invoke(tools.todo_delete, id="不存在")
    assert missing["success"] is False
    assert missing["deleted"] is False


def test_todo_meta_get_initializes_and_count_live(plugin_data_dir) -> None:
    """todo_meta_get 缺失时初始化侧车，且 count 实时反映 todo.json。"""
    first = _invoke(tools.todo_meta_get)
    assert first["success"] is True
    assert first["meta"]["count"] == 0
    assert (plugin_data_dir / "todo-meta.json").exists()

    _invoke(tools.todo_save, items=[_item("1", "买牛奶"), _item("2", "写周报")])
    second = _invoke(tools.todo_meta_get)
    assert second["meta"]["count"] == 2
    assert second["meta"]["createdAt"] == first["meta"]["createdAt"]


def test_todo_meta_stamp_changes_created_at(plugin_data_dir) -> None:
    """todo_meta_stamp 会刷新 createdAt 与 count。"""
    _invoke(tools.todo_save, items=[_item("1", "买牛奶")])
    before = _invoke(tools.todo_meta_get)["meta"]["createdAt"]

    stamped = _invoke(tools.todo_meta_stamp)
    assert stamped["success"] is True
    assert stamped["meta"]["count"] == 1
    assert stamped["meta"]["createdAt"] != before
    assert stamped["meta"]["date"] == datetime.now().strftime("%Y-%m-%d")


def test_todo_save_rejects_has_synced(plugin_data_dir) -> None:
    """写入含 HasSynced 的记录必须失败，保护协议。"""
    bad_item = {**_item("1"), "HasSynced": True}
    result = _invoke(tools.todo_save, items=[bad_item])
    assert result["success"] is False
    assert "HasSynced" in result["error"]
    assert not (plugin_data_dir / "todo.json").exists()
