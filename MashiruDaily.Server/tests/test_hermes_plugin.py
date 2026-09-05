"""hermes_plugin 工具的离线契约测试。

不依赖 FastAPI / Hermes 进程，只验证插件内的 todo_* handler：
- todo.json / todo-meta.json 的读写均通过 handler 返回的 JSON 字符串；
- 临时数据目录由 MASHIRU_DATA_DIR 注入，测试后自动还原。
"""

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

# 保证可以 import hermes_plugin（Server 根目录）
SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from hermes_plugin.mashiru_daily import tools  # noqa: E402

CST = timezone(timedelta(hours=8))


def _invoke(handler, **kwargs) -> dict:
    """调用 handler 并解析返回的 JSON 字符串。"""
    return json.loads(handler(kwargs))


def _assert_valid_item(item: dict, title: str | None = None) -> None:
    """校验程序生成的待办记录字段完整且语义一致。"""
    assert set(item.keys()) == {"id", "title", "is_completed", "created_at", "completed_at"}
    uuid.UUID(item["id"])
    assert item["title"]
    assert isinstance(item["is_completed"], bool)
    assert item["created_at"]
    assert item["created_at"].endswith("+08:00")
    if title is not None:
        assert item["title"] == title
    if item["is_completed"]:
        assert item["completed_at"] is not None
    else:
        assert item["completed_at"] is None


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
    """todo_save 只接收 title 数组，程序生成完整待办后 todo_list 能读回。"""
    titles = ["买牛奶", "写周报"]
    saved = _invoke(tools.todo_save, items=titles)
    assert saved["success"] is True
    assert saved["count"] == 2

    listed = _invoke(tools.todo_list)
    assert [item["title"] for item in listed["items"]] == titles
    for item in listed["items"]:
        _assert_valid_item(item)
        assert item["is_completed"] is False
        assert item["completed_at"] is None


def test_todo_save_full_rebuild_generates_new_ids(plugin_data_dir) -> None:
    """todo_save 全量重建时每次都为标题生成新 id。"""
    _invoke(tools.todo_save, items=["买牛奶"])
    first_id = _invoke(tools.todo_list)["items"][0]["id"]

    _invoke(tools.todo_save, items=["买牛奶"])
    second_id = _invoke(tools.todo_list)["items"][0]["id"]

    assert first_id != second_id


def test_todo_save_archives_existing_file_before_overwrite(plugin_data_dir) -> None:
    """todo_save 覆盖前先把旧 todo.json 存档到 data/backups/。"""
    _invoke(tools.todo_save, items=["买牛奶"])
    assert not (plugin_data_dir / "backups").exists()

    _invoke(tools.todo_save, items=["写周报"])
    backup_files = list((plugin_data_dir / "backups").glob("todo-*.json"))
    assert len(backup_files) == 1
    archived = json.loads(backup_files[0].read_text(encoding="utf-8"))
    assert [item["title"] for item in archived] == ["买牛奶"]

    listed = _invoke(tools.todo_list)
    assert [item["title"] for item in listed["items"]] == ["写周报"]


def test_todo_upsert_without_id_generates_id(plugin_data_dir) -> None:
    """todo_upsert 缺 id 时自动生成 id，并新增待办。"""
    result = _invoke(tools.todo_upsert, title="买菜", is_completed=False)
    assert result["success"] is True
    assert result["created"] is True
    uuid.UUID(result["item"]["id"])
    assert result["item"]["title"] == "买菜"
    assert result["item"]["is_completed"] is False


def test_todo_upsert_requires_title(plugin_data_dir) -> None:
    """todo_upsert 必须传入非空 title。"""
    result = _invoke(tools.todo_upsert, id=str(uuid.uuid4()), title="", is_completed=False, completed_at=None)
    assert result["success"] is False
    assert "title" in result["error"]


def test_todo_upsert_requires_is_completed(plugin_data_dir) -> None:
    """todo_upsert 必须传入 is_completed。"""
    result = _invoke(tools.todo_upsert, id=str(uuid.uuid4()), title="买菜", completed_at=None)
    assert result["success"] is False
    assert "is_completed" in result["error"]


def test_todo_upsert_without_completed_at_defaults_null(plugin_data_dir) -> None:
    """todo_upsert 缺 completed_at 时允许执行，新建条目的 completed_at 为 null。"""
    result = _invoke(tools.todo_upsert, id=str(uuid.uuid4()), title="买菜", is_completed=False)
    assert result["success"] is True
    assert result["item"]["completed_at"] is None


def test_todo_upsert_creates_with_new_id(plugin_data_dir) -> None:
    """todo_upsert 传入不存在的 id 时新建该 id 的待办，id 不再由程序另生成。"""
    item_id = str(uuid.uuid4())
    result = _invoke(tools.todo_upsert, id=item_id, title="买菜", is_completed=False, completed_at=None)
    assert result["success"] is True
    assert result["created"] is True
    assert result["count"] == 1
    _assert_valid_item(result["item"], title="买菜")
    assert result["item"]["id"] == item_id


def test_todo_upsert_updates_title_with_existing_id(plugin_data_dir) -> None:
    """todo_upsert 传入已存在 id 时更新标题/完成状态/完成时间，保留原 id/created_at。"""
    item_id = str(uuid.uuid4())
    added = _invoke(tools.todo_upsert, id=item_id, title="买菜", is_completed=False, completed_at=None)
    created_at = added["item"]["created_at"]
    completed_at = "2026-08-17T18:00:00+08:00"

    updated = _invoke(
        tools.todo_upsert,
        id=item_id,
        title="买菜并记账",
        is_completed=True,
        completed_at=completed_at,
    )
    assert updated["success"] is True
    assert updated["created"] is False
    assert updated["item"]["id"] == item_id
    assert updated["item"]["title"] == "买菜并记账"
    assert updated["item"]["created_at"] == created_at
    assert updated["item"]["is_completed"] is True
    assert updated["item"]["completed_at"] == completed_at


def test_todo_completed_marks_complete_and_reopens(plugin_data_dir) -> None:
    """todo_completed 修改完成状态，completed_at 与客户端传入值同步。"""
    added = _invoke(tools.todo_upsert, id=str(uuid.uuid4()), title="买菜", is_completed=False, completed_at=None)
    item_id = added["item"]["id"]
    completed_at = "2026-08-17T18:00:00+08:00"

    done = _invoke(tools.todo_completed, id=item_id, completed=True, completed_at=completed_at)
    assert done["success"] is True
    assert done["item"]["is_completed"] is True
    assert done["item"]["completed_at"] == completed_at

    reopened = _invoke(tools.todo_completed, id=item_id, completed=False, completed_at=None)
    assert reopened["success"] is True
    assert reopened["item"]["is_completed"] is False
    assert reopened["item"]["completed_at"] is None


def test_todo_completed_rejects_missing_id(plugin_data_dir) -> None:
    """todo_completed 找不到 id 时返回 success=false。"""
    result = _invoke(tools.todo_completed, id="不存在", completed=True, completed_at=None)
    assert result["success"] is False
    assert result["found"] is False


def test_todo_completed_rejects_non_bool(plugin_data_dir) -> None:
    """todo_completed 的 completed 必须是布尔值。"""
    result = _invoke(tools.todo_completed, id="x", completed="yes", completed_at=None)
    assert result["success"] is False


def test_todo_completed_requires_completed_at(plugin_data_dir) -> None:
    """todo_completed 必须传入 completed_at。"""
    result = _invoke(tools.todo_completed, id=str(uuid.uuid4()), completed=True)
    assert result["success"] is False
    assert "completed_at" in result["error"]


def test_todo_delete_removes_by_id(plugin_data_dir) -> None:
    """todo_delete 按 id 删除；不存在时返回 success=false 且 deleted=false。"""
    _invoke(tools.todo_save, items=["买牛奶", "写周报"])
    item_id = _invoke(tools.todo_list)["items"][0]["id"]

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
    assert second["meta"]["updated_at"] == first["meta"]["updated_at"]


def test_todo_meta_stamp_changes_updated_at(plugin_data_dir) -> None:
    """todo_meta_stamp 会刷新 updated_at 与 count。"""
    _invoke(tools.todo_save, items=["买牛奶"])
    before = _invoke(tools.todo_meta_get)["meta"]["updated_at"]

    stamped = _invoke(tools.todo_meta_stamp)
    assert stamped["success"] is True
    assert stamped["meta"]["count"] == 1
    assert stamped["meta"]["updated_at"] != before
    assert stamped["meta"]["date"] == datetime.now(CST).strftime("%Y-%m-%d")


def test_todo_save_rejects_non_string_title(plugin_data_dir) -> None:
    """todo_save 只允许 title 数组，非字符串元素必须失败。"""
    result = _invoke(tools.todo_save, items=[{"title": "x"}])
    assert result["success"] is False
    assert "title" in result["error"]
    assert not (plugin_data_dir / "todo.json").exists()


def test_speak_to_user_writes_message_file(plugin_data_dir) -> None:
    """speak_to_user 应把消息写到数据目录父目录的 messages-to-user.json。"""
    result = _invoke(tools.speak_to_user, text="记得完成数学作业")
    assert result["success"] is True

    msg_path = plugin_data_dir.parent / "messages-to-user.json"
    assert msg_path.exists()
    data = json.loads(msg_path.read_text(encoding="utf-8"))
    assert data["text"] == "记得完成数学作业"
    assert data["time"].endswith("+08:00")


def test_speak_to_user_rejects_non_string(plugin_data_dir) -> None:
    """speak_to_user 的 text 必须是字符串；非法输入不写文件。"""
    result = _invoke(tools.speak_to_user, text=123)
    assert result["success"] is False
    assert not (plugin_data_dir.parent / "messages-to-user.json").exists()
