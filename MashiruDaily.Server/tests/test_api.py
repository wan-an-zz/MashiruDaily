"""GET /api/todo 与 GET /api/todo/meta 的 API 集成测试。

面向后续任务中的 app/main.py 编写（测试优先）：本文件在模块顶层只导入
标准库与 pytest，app.main 在 fixture 内懒加载——当前阶段 app.main 尚不
存在，用例会以 ERROR 呈现（预期的 RED 状态），待 main.py 落地后自动转绿。
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import TypedDict

import pytest

# Server 根目录：用于定位 tools/stamp_todo_meta.py（用例 f 的子进程调用）
SERVER_ROOT = Path(__file__).resolve().parent.parent


class _TodoFixture(TypedDict):
    """测试用的 PascalCase 待办条目（与 C# 端契约一致）。"""

    Id: str
    Title: str
    IsCompleted: bool
    CreatedAt: str
    CompletedAt: str | None


def _atomic_write(path: Path, content: str) -> None:
    """以 tmp + os.replace 原子方式写入测试数据文件（与生产代码同一落盘策略）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(content, encoding="utf-8")
    os.replace(tmp_path, path)


def _item(todo_id: str, title: str) -> _TodoFixture:
    """构造一条符合契约的待办记录。"""
    return {
        "Id": todo_id,
        "Title": title,
        "IsCompleted": False,
        "CreatedAt": "2026-08-12T08:00:00+08:00",
        "CompletedAt": None,
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
    """应返回 200：date 为 yyyy-MM-dd，createdAt 为可解析的 ISO8601 UTC，count 为整数。"""
    # Given: 空数据目录（无 todo.json、无侧车）

    # When: 请求元数据
    resp = client.get("/api/todo/meta")

    # Then: 结构合法
    assert resp.status_code == 200
    body = resp.json()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", body["date"])
    assert body["createdAt"].endswith("Z") or body["createdAt"].endswith("+00:00")
    created_at = datetime.fromisoformat(body["createdAt"])
    assert created_at.tzinfo is not None
    assert isinstance(body["count"], int)


def test_todo_echoes_pascalcase_verbatim(client, data_dir) -> None:
    """应 200 返回数组，逐字回显 PascalCase 字段；无 HasSynced，CompletedAt 为 null。"""
    # Given: 写入含精确 PascalCase 键的 todo.json
    items: list[_TodoFixture] = [
        {
            "Id": "5f2f0d9e-4f6f-4f3e-9a3e-1234567890ab",
            "Title": "写周报",
            "IsCompleted": False,
            "CreatedAt": "2026-08-12T08:00:00+08:00",
            "CompletedAt": None,
        },
        {
            "Id": "7c1a2b3c-0000-0000-0000-000000000001",
            "Title": "买牛奶",
            "IsCompleted": True,
            "CreatedAt": "2026-08-12T09:00:00+08:00",
            "CompletedAt": "2026-08-12T10:30:00+08:00",
        },
    ]
    _atomic_write(data_dir / "todo.json", json.dumps(items, ensure_ascii=False))

    # When: 请求待办列表
    resp = client.get("/api/todo")

    # Then: 与写入值逐字一致，键名恰为五个 PascalCase 字段
    assert resp.status_code == 200
    assert resp.json() == items
    for item in resp.json():
        assert set(item.keys()) == {"Id", "Title", "IsCompleted", "CreatedAt", "CompletedAt"}
        assert "HasSynced" not in item
    assert resp.json()[0]["CompletedAt"] is None


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


def test_created_at_survives_webhook_edit_but_stamp_changes_it(client, data_dir) -> None:
    """webhook 式编辑后 createdAt 不变（count 增加）；stamp_todo_meta.py 运行后 createdAt 改变。"""
    # Given: 初始 todo.json 与侧车
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶")], ensure_ascii=False),
    )
    meta_before = client.get("/api/todo/meta").json()
    created_before = meta_before["createdAt"]

    # When: 模拟 webhook 编辑（追加一条）后请求 meta
    _atomic_write(
        data_dir / "todo.json",
        json.dumps([_item("1", "买牛奶"), _item("2", "写周报")], ensure_ascii=False),
    )
    meta_after_edit = client.get("/api/todo/meta").json()

    # Then: createdAt 不变，count 增加
    assert meta_after_edit["createdAt"] == created_before
    assert meta_after_edit["count"] == meta_before["count"] + 1

    # When: 以子进程运行 stamp_todo_meta.py（携带 MASHIRU_DATA_DIR）
    stamp_script = SERVER_ROOT / "tools" / "stamp_todo_meta.py"
    subprocess.run(
        [sys.executable, str(stamp_script)],
        cwd=SERVER_ROOT,
        env={**os.environ, "MASHIRU_DATA_DIR": str(data_dir)},
        capture_output=True,
        timeout=60,
        check=True,
    )

    # Then: createdAt 已改变且为合法 UTC，date 为今日，count 匹配实时条数
    meta_after_stamp = client.get("/api/todo/meta").json()
    assert meta_after_stamp["createdAt"] != created_before
    assert meta_after_stamp["date"] == datetime.now().strftime("%Y-%m-%d")
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
