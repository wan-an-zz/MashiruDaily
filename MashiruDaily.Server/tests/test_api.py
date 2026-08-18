"""GET /api/todo 与 GET /api/todo/meta 的 API 集成测试。

面向后续任务中的 app/main.py 编写（测试优先）：本文件在模块顶层只导入
标准库与 pytest，app.main 在 fixture 内懒加载——当前阶段 app.main 尚不
存在，用例会以 ERROR 呈现（预期的 RED 状态），待 main.py 落地后自动转绿。
"""

import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TypedDict

import pytest

# Server 根目录：用于在用例内导入 hermes_plugin 的 todo_meta_stamp
SERVER_ROOT = Path(__file__).resolve().parent.parent
CST = timezone(timedelta(hours=8))


class _TodoFixture(TypedDict):
    """测试用的 snake_case 待办条目（与 C# 端契约一致）。"""

    id: str
    title: str
    is_completed: bool
    created_at: str
    completed_at: str | None


def _atomic_write(path: Path, content: str) -> None:
    """以 tmp + os.replace 原子方式写入测试数据文件（与生产代码同一落盘策略）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def _item(todo_id: str, title: str) -> _TodoFixture:
    """构造一条符合契约的待办记录。"""
    return {
        "id": todo_id,
        "title": title,
        "is_completed": False,
        "created_at": "2026-08-12T08:00:00+08:00",
        "completed_at": None,
    }


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """为每个测试准备独立的临时数据目录，并让服务端配置指向它。

    先设置 MASHIRU_DATA_DIR 再清空 get_settings 的缓存，确保下一次调用
    按新目录重建；monkeypatch 在测试结束后自动还原环境变量。
    """
    monkeypatch.setenv("MASHIRU_DATA_DIR", str(tmp_path))
    from app.config import get_settings

    get_settings.cache_clear()
    return tmp_path


@pytest.fixture()
def client(data_dir: Path):
    """懒加载 app.main（本阶段尚不存在，落地后自动可运行）。"""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


def test_meta_returns_valid_shape(client, data_dir) -> None:
    """应返回 200：date 为 yyyy-MM-dd，created_at 为可解析的 ISO8601 UTC+8，count 为整数。"""
    # Given: 空数据目录（无 todo.json、无侧车）

    # When: 请求元数据
    resp = client.get("/api/todo/meta")

    # Then: 结构合法
    assert resp.status_code == 200
    body = resp.json()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["date"])
    assert body["created_at"].endswith("+08:00")
    created_at = datetime.fromisoformat(body["created_at"])
    assert created_at.tzinfo is not None
    assert isinstance(body["count"], int)


def test_todo_echoes_snake_case_verbatim(client, data_dir) -> None:
    """应 200 返回数组，逐字回显 snake_case 字段；无 has_synced，completed_at 为 null。"""
    # Given: 写入含精确 snake_case 键的 todo.json
    items: list[_TodoFixture] = [
        {
            "id": "5f2f0d9e-4f6f-4f3e-9a3e-1234567890ab",
            "title": "写周报",
            "is_completed": False,
            "created_at": "2026-08-12T08:00:00+08:00",
            "completed_at": None,
        },
        {
            "id": "7c1a2b3c-0000-0000-0000-000000000001",
            "title": "买牛奶",
            "is_completed": True,
            "created_at": "2026-08-12T09:00:00+08:00",
            "completed_at": "2026-08-12T10:30:00+08:00",
        },
    ]
    _atomic_write(data_dir / "todo.json", json.dumps(items, ensure_ascii=False))

    # When: 请求待办列表
    resp = client.get("/api/todo")

    # Then: 与写入值逐字一致，键名恰为五个 snake_case 字段
    assert resp.status_code == 200
    assert resp.json() == items
    for item in resp.json():
        assert set(item.keys()) == {"id", "title", "is_completed", "created_at", "completed_at"}
        assert "has_synced" not in item
    assert resp.json()[0]["completed_at"] is None


def test_todo_empty_and_meta_count_zero_without_file(client, data_dir) -> None:
    """todo.json 缺失时 GET /api/todo 返回空数组 200，meta 的 count 为 0。"""
    # Given: 空数据目录（无 todo.json）

    # When: 请求待办列表与元数据
    todo_resp = client.get("/api/todo")
    meta_resp = client.get("/api/todo/meta")

    # Then: 空数组与 count=0
    assert todo_resp.status_code == 200
    assert todo_resp.json() == []
    assert meta_resp.status_code == 200
    assert meta_resp.json()["count"] == 0


def test_meta_creates_sidecar_on_first_boot(client, data_dir) -> None:
    """首次启动无 todo-meta.json 时，GET /api/todo/meta 仍 200 并创建侧车。"""
    # Given: 空数据目录（无侧车）
    assert not (data_dir / "todo-meta.json").exists()

    # When: 请求元数据
    resp = client.get("/api/todo/meta")

    # Then: 200 且侧车已生成
    assert resp.status_code == 200
    assert (data_dir / "todo-meta.json").exists()


def test_malformed_todo_json_returns_500(client, data_dir) -> None:
    """todo.json 为非法 JSON 时，GET /api/todo 应返回 500（由 main.py 将 ValueError 映射为 500）。"""
    # Given: 写入非法 JSON
    _atomic_write(data_dir / "todo.json", "{这不是合法 JSON")

    # When: 请求待办列表
    resp = client.get("/api/todo")

    # Then: 500
    assert resp.status_code == 500


def test_meta_sidecar_malformed_shape_returns_json_500(client, data_dir) -> None:
    """todo-meta.json 可解析但结构缺键时，GET /api/todo/meta 应返回 500 且 body 为 JSON detail。

    回归防护：修复前 _read_meta 不校验形状，current_meta 的 meta["date"] 会抛 KeyError，
    落到 FastAPI 默认 500 HTML；修复后统一走 ValueError→500 JSON，与其余错误路径一致。
    """
    # Given: 写入缺键的侧车（如手改或旧版本产生）
    _atomic_write(data_dir / "todo-meta.json", '{"date": "2026-08-12"}')

    # When: 请求元数据
    resp = client.get("/api/todo/meta")

    # Then: 500 且为 JSON 错误体（非 HTML 错误页）
    assert resp.status_code == 500
    body = resp.json()
    assert "detail" in body


def test_meta_sidecar_non_object_returns_json_500(client, data_dir) -> None:
    """todo-meta.json 顶层不是对象（如数组/字符串）时同样返回 500 JSON。"""
    # Given: 写入顶层为数组的侧车
    _atomic_write(data_dir / "todo-meta.json", "[1, 2, 3]")

    # When: 请求元数据
    resp = client.get("/api/todo/meta")

    # Then: 500 且为 JSON 错误体
    assert resp.status_code == 500
    assert "detail" in resp.json()


def test_created_at_survives_webhook_edit_but_stamp_changes_it(client, data_dir) -> None:
    """webhook 式编辑后 created_at 不变（count 增加）；todo_meta_stamp 运行后 created_at 改变。"""
    # Given: 初始 todo.json 与侧车
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶")], ensure_ascii=False),
    )
    meta_before = client.get("/api/todo/meta").json()
    created_before = meta_before["created_at"]

    # When: 模拟 webhook 编辑（追加一条）后请求 meta
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶"), _item("2", "写周报")], ensure_ascii=False),
    )
    meta_after_edit = client.get("/api/todo/meta").json()

    # Then: created_at 不变，count 增加
    assert meta_after_edit["created_at"] == created_before
    assert meta_after_edit["count"] == meta_before["count"] + 1

    # When: 调用插件工具 todo_meta_stamp（MASHIRU_DATA_DIR 已由 fixture 指向临时目录）
    if str(SERVER_ROOT) not in sys.path:
        sys.path.insert(0, str(SERVER_ROOT))
    from hermes_plugin.mashiru_daily.tools import todo_meta_stamp

    stamp_result = json.loads(todo_meta_stamp({}))
    assert stamp_result["success"] is True

    # Then: created_at 已改变且为合法 UTC+8，date 为今日，count 匹配实时条数
    meta_after_stamp = client.get("/api/todo/meta").json()
    assert meta_after_stamp["created_at"] != created_before
    assert meta_after_stamp["date"] == datetime.now(CST).strftime("%Y-%m-%d")
    assert meta_after_stamp["count"] == 2


def test_meta_count_is_live(client, data_dir) -> None:
    """外部修改 todo.json 后，meta 的 count 反映实时条目数（而非侧车中的旧值）。"""
    # Given: 侧车存在且 count 为 1
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶")], ensure_ascii=False),
    )
    assert client.get("/api/todo/meta").json()["count"] == 1

    # When: 外部新增两条（模拟 Hermes 修改 todo.json）
    _atomic_write(
        data_dir / "todo.json",
        json.dumps(
            [_item("1", "买牛奶"), _item("2", "写周报"), _item("3", "买菜")],
            ensure_ascii=False,
        ),
    )

    # Then: count 实时反映为 3
    assert client.get("/api/todo/meta").json()["count"] == 3


def _update_envelope(event_type: str, item: _TodoFixture) -> dict:
    """构造一条与 C# 端 HermesSyncService.SendAsync 逐字段一致的推送事件。

    客户端序列化使用 snake_case：event_type / timestamp / payload 三层嵌套，
    payload 内恰为 id/title/is_completed/created_at/completed_at 五个字段。
    """
    return {
        "event_type": event_type,
        "timestamp": "2026-08-18T09:00:00+08:00",
        "payload": dict(item),
    }


def _update_body(*events: dict) -> dict:
    """构造 POST /api/update 的请求体：顶层 event_type + events 数组。"""
    return {"event_type": "update", "events": list(events)}


def test_update_upserts_todo_list(client, data_dir) -> None:
    """POST /api/update 推送 todo_updated 应 200，返回 success_ids，且新条目落入 todo.json。"""
    # Given: 服务器已有 1 条待办
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶")], ensure_ascii=False),
    )

    # When: 客户端推送一条新待办（todo_updated 视为 upsert）
    new_item = _item("2", "写周报")
    resp = client.post("/api/update", json=_update_body(_update_envelope("todo_updated", new_item)))

    # Then: 200，success_ids 包含新 id，error_ids 为空，todo.json 已追加
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["success_ids"] == ["2"]
    assert body["error_ids"] == []
    assert client.get("/api/todo").json() == [_item("1", "买牛奶"), new_item]


def test_update_deletes_todo(client, data_dir) -> None:
    """POST /api/update 推送 todo_deleted 应 200，并从 todo.json 移除该条目。"""
    # Given: 服务器已有 2 条待办
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶"), _item("2", "写周报")], ensure_ascii=False),
    )

    # When: 客户端推送删除 id=1
    resp = client.post("/api/update", json=_update_body(_update_envelope("todo_deleted", _item("1", "买牛奶"))))

    # Then: 200 且仅剩 id=2
    assert resp.status_code == 200
    assert resp.json()["success"] is True
    assert resp.json()["success_ids"] == ["1"]
    assert client.get("/api/todo").json() == [_item("2", "写周报")]


def test_update_batch_mixed_upsert_and_delete(client, data_dir) -> None:
    """单批同时含 upsert 与 delete 事件时应逐条生效，全部计入 success_ids。"""
    # Given: 服务器已有 2 条待办
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶"), _item("2", "写周报")], ensure_ascii=False),
    )

    # When: 同一批推送新增 id=3 与删除 id=1
    new_item = _item("3", "买菜")
    resp = client.post(
        "/api/update",
        json=_update_body(
            _update_envelope("todo_updated", new_item),
            _update_envelope("todo_deleted", _item("1", "买牛奶")),
        ),
    )

    # Then: 200，两条 id 均在 success_ids，列表为 [id=2, id=3]
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert sorted(body["success_ids"]) == ["1", "3"]
    assert client.get("/api/todo").json() == [_item("2", "写周报"), new_item]


def test_update_delete_missing_id_returns_500_error_ids(client, data_dir) -> None:
    """删除不存在的 id 应返回 500，body 携带 error_ids，且 todo.json 保持不变。

    回归防护：todo_delete 对缺失 id 返回 success=False，端点必须把它映射到
    error_ids 并返回 500，而不是把 500 留给异常兜底。
    """
    # Given: 服务器已有 1 条待办
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶")], ensure_ascii=False),
    )

    # When: 客户端推送删除不存在的 id=999
    resp = client.post("/api/update", json=_update_body(_update_envelope("todo_deleted", _item("999", "幽灵"))))

    # Then: 500，error_ids 含 999，数据未被改动
    assert resp.status_code == 500
    body = resp.json()
    assert body["success"] is False
    assert body["error_ids"] == ["999"]
    assert client.get("/api/todo").json() == [_item("1", "买牛奶")]


def test_update_rejects_malformed_body(client, data_dir) -> None:
    """请求体缺少必需字段（如 events 缺失）应返回 422（FastAPI 校验兜底）。"""
    # When: 推送空对象
    resp = client.post("/api/update", json={})

    # Then: 422
    assert resp.status_code == 422
