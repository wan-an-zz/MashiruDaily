"""数据目录默认位置的契约测试。

需求：todo.json / todo-meta.json 的存储位置从项目文件夹的 data/ 迁移到
$HOME/.mashiru-daily/todos/。本文件验证「未设置 MASHIRU_DATA_DIR 环境变量时」，
服务端配置与插件工具都默认解析到 ~/.mashiru-daily/todos（而非旧的 Server/data）。
MASHIRU_DATA_DIR 仍作为显式覆盖手段保留（由既有 fixture 测试覆盖）。

开发采用 TDD：先写本文件（RED），再修改 app/config.py 与
hermes_plugin/mashiru_daily/tools.py 的默认路径使测试转绿。
"""

import os
import sys
from pathlib import Path

import pytest

# Server 根目录：保证可 import app 与 hermes_plugin
SERVER_ROOT = Path(__file__).resolve().parent.parent
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

EXPECTED_DEFAULT = Path.home() / ".mashiru-daily" / "todos"


@pytest.fixture(autouse=True)
def _clear_env_and_cache(monkeypatch):
    """确保测试不继承外部 MASHIRU_DATA_DIR，并清空 get_settings 缓存。"""
    monkeypatch.delenv("MASHIRU_DATA_DIR", raising=False)
    from app.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_server_settings_defaults_to_home_todos() -> None:
    """未设置 MASHIRU_DATA_DIR 时，get_settings().data_dir 应解析为 ~/.mashiru-daily/todos。"""
    from app.config import get_settings

    assert get_settings().data_dir == EXPECTED_DEFAULT


def test_server_settings_equals_constant() -> None:
    """DEFAULT_DATA_DIR 常量本身也应等于 ~/.mashiru-daily/todos（单一事实源）。"""
    from app.config import DEFAULT_DATA_DIR

    assert DEFAULT_DATA_DIR == EXPECTED_DEFAULT


def test_plugin_tools_data_dir_defaults_to_home_todos() -> None:
    """未设置 MASHIRU_DATA_DIR 时，hermes_plugin 的 _data_dir() 应解析为 ~/.mashiru-daily/todos。"""
    from hermes_plugin.mashiru_daily.tools import _data_dir

    assert _data_dir() == EXPECTED_DEFAULT


def test_plugin_todo_and_meta_paths_under_home_todos() -> None:
    """插件工具的 todo.json 与 todo-meta.json 路径应位于 ~/.mashiru-daily/todos 下。"""
    from hermes_plugin.mashiru_daily.tools import _meta_path, _todo_path

    assert _todo_path() == EXPECTED_DEFAULT / "todo.json"
    assert _meta_path() == EXPECTED_DEFAULT / "todo-meta.json"


def test_uninstall_default_data_dir_is_home_todos(monkeypatch) -> None:
    """uninstall 的 _remove_data 在无 MASHIRU_DATA_DIR 时，默认数据目录应为 ~/.mashiru-daily/todos。

    回归防护：_remove_data 内部用 `os.environ.get("MASHIRU_DATA_DIR", 默认)` 解析，
    这里通过 monkeypatch 记录 rmtree 目标来断言默认值指向新位置。
    """
    import uninstall

    monkeypatch.delenv("MASHIRU_DATA_DIR", raising=False)
    rmtree_targets: list[Path] = []

    def fake_rmtree(path, **kwargs):
        rmtree_targets.append(Path(path))

    monkeypatch.setattr(uninstall.shutil, "rmtree", fake_rmtree)

    # 用假目录让 is_dir() 通过（默认数据目录应指向新位置）
    monkeypatch.setattr(Path, "is_dir", lambda self: True)
    monkeypatch.setattr(Path, "exists", lambda self: True)
    monkeypatch.setattr("uninstall._confirm", lambda *a, **k: True)

    ok = uninstall._remove_data(dry_run=False, keep=False, yes=True)
    assert ok is True
    assert len(rmtree_targets) == 1
    assert rmtree_targets[0] == EXPECTED_DEFAULT
