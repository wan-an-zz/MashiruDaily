"""hermes_plugin 工具的离线契约测试。

不依赖 FastAPI / Hermes 进程，只验证插件内的 todo_* handler：
- todo.json / todo-meta.json 的读写均通过 handler 返回的 JSON 字符串；
- 临时数据目录由 MASHIRU_DATA_DIR 注入，测试后自动还原。
"""

import json
import sys
import uuid
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


def _assert_valid_item(item: dict, title: str | None = None) -> None:
    """校验程序生成的待办记录字段完整且语义一致。"""
    assert set(item.keys()) == {"Id", "Title", "IsCompleted", "CreatedAt", "CompletedAt"}
    uuid.UUID(item["Id"])
    assert item["Title"]
    assert isinstance(item["IsCompleted"], bool)
    assert item["CreatedAt"]
    if title is not None:
        assert item["Title"] == title
    if item["IsCompleted"]:
        assert item["CompletedAt"] is not None
    else:
        assert item["CompletedAt"] is None


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
    """todo_save 只接收 Title 数组，程序生成完整待办后 todo_list 能读回。"""
    titles = ["买牛奶", "写周报"]
    saved = _invoke(tools.todo_save, items=titles)
    assert saved["success"] is True
    assert saved["count"] == 2

    listed = _invoke(tools.todo_list)
    assert [item["Title"] for item in listed["items"]] == titles
    for item in listed["items"]:
        _assert_valid_item(item)
        assert item["IsCompleted"] is False
        assert item["CompletedAt"] is None


def test_todo_save_full_rebuild_generates_new_ids(plugin_data_dir) -> None:
    """todo_save 全量重建时每次都为标题生成新 Id。"""
    _invoke(tools.todo_save, items=["买牛奶"])
    first_id = _invoke(tools.todo_list)["items"][0]["Id"]

    _invoke(tools.todo_save, items=["买牛奶"])
    second_id = _invoke(tools.todo_list)["items"][0]["Id"]

    assert first_id != second_id


def test_todo_upsert_adds_without_id(plugin_data_dir) -> None:
    """todo_upsert 未传 Id 时新增待办，Id/CreatedAt 由程序生成。"""
    result = _invoke(tools.todo_upsert, title="买菜")
    assert result["success"] is True
    assert result["created"] is True
    assert result["count"] == 1
    _assert_valid_item(result["item"], title="买菜")


def test_todo_upsert_updates_title_with_existing_id(plugin_data_dir) -> None:
    """todo_upsert 传入已存在 Id 时只更新标题，保留原 Id/CreatedAt。"""
    added = _invoke(tools.todo_upsert, title="买菜")
    item_id = added["item"]["Id"]
    created_at = added["item"]["CreatedAt"]

    updated = _invoke(tools.todo_upsert, id=item_id, title="买菜并记账")
    assert updated["success"] is True
    assert updated["created"] is False
    assert updated["item"]["Id"] == item_id
    assert updated["item"]["Title"] == "买菜并记账"
    assert updated["item"]["CreatedAt"] == created_at
    assert updated["item"]["IsCompleted"] is False


def test_todo_upsert_rejects_unknown_id(plugin_data_dir) -> None:
    """todo_upsert 传入不存在的 Id 时不创建新记录，避免 Agent 编造 Id。"""
    result = _invoke(tools.todo_upsert, id="不存在", title="测试")
    assert result["success"] is False
    assert result["found"] is False


def test_todo_completed_marks_complete_and_reopens(plugin_data_dir) -> None:
    """todo_completed 修改完成状态，CompletedAt 由程序生成或清空。"""
    added = _invoke(tools.todo_upsert, title="买菜")
    item_id = added["item"]["Id"]

    done = _invoke(tools.todo_completed, id=item_id, completed=True)
    assert done["success"] is True
    assert done["item"]["IsCompleted"] is True
    assert done["item"]["CompletedAt"] is not None

    reopened = _invoke(tools.todo_completed, id=item_id, completed=False)
    assert reopened["success"] is True
    assert reopened["item"]["IsCompleted"] is False
    assert reopened["item"]["CompletedAt"] is None


def test_todo_completed_rejects_missing_id(plugin_data_dir) -> None:
    """todo_completed 找不到 Id 时返回 success=false。"""
    result = _invoke(tools.todo_completed, id="不存在", completed=True)
    assert result["success"] is False
    assert result["found"] is False


def test_todo_completed_rejects_non_bool(plugin_data_dir) -> None:
    """todo_completed 的 completed 必须是布尔值。"""
    result = _invoke(tools.todo_completed, id="x", completed="yes")
    assert result["success"] is False


def test_todo_delete_removes_by_id(plugin_data_dir) -> None:
    """todo_delete 按 Id 删除；不存在时返回 success=false 且 deleted=false。"""
    _invoke(tools.todo_save, items=["买牛奶", "写周报"])
    item_id = _invoke(tools.todo_list)["items"][0]["Id"]

    deleted = _invoke(tools.todo_delete, id=item_id)
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

    _invoke(tools.todo_save, items=["买牛奶", "写周报"])
    second = _invoke(tools.todo_meta_get)
    assert second["meta"]["count"] == 2
    assert second["meta"]["createdAt"] == first["meta"]["createdAt"]


def test_todo_meta_stamp_changes_created_at(plugin_data_dir) -> None:
    """todo_meta_stamp 会刷新 createdAt 与 count。"""
    _invoke(tools.todo_save, items=["买牛奶"])
    before = _invoke(tools.todo_meta_get)["meta"]["createdAt"]

    stamped = _invoke(tools.todo_meta_stamp)
    assert stamped["success"] is True
    assert stamped["meta"]["count"] == 1
    assert stamped["meta"]["createdAt"] != before
    assert stamped["meta"]["date"] == datetime.now().strftime("%Y-%m-%d")


def test_todo_save_rejects_non_string_title(plugin_data_dir) -> None:
    """todo_save 只允许 Title 数组，非字符串元素必须失败。"""
    result = _invoke(tools.todo_save, items=[{"Title": "x"}])
    assert result["success"] is False
    assert "Title" in result["error"]
    assert not (plugin_data_dir / "todo.json").exists()
