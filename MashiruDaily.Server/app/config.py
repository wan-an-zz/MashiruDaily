"""服务端配置：读取环境变量并构建进程内缓存的不可变 Settings。"""

import os
import sys
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final

# Server 根目录：本文件位于 <根>/app/，上溯一级即根目录。
# 所有默认路径都基于它解析，绝不依赖 os.getcwd()——服务器可能由计划任务
# 以不同的工作目录启动，cwd 不可信。
SERVER_ROOT: Final[Path] = Path(__file__).resolve().parent.parent

# 默认数据目录：$HOME/.mashiru-daily/todos（todo.json / todo-meta.json 所在地）。
# 从项目文件夹 data/ 迁移而来：数据不再与源码仓库耦合，且不受 cwd / 部署位置影响。
DEFAULT_DATA_DIR: Final[Path] = Path.home() / ".mashiru-daily" / "todos"


@dataclass(frozen=True, slots=True)
class Settings:
    """服务端运行配置（不可变值对象）。

    data_dir：数据目录（todo.json / todo-meta.json 所在地）；
    host / port：HTTP 监听地址；
    hermes_home：Hermes 宿主目录（本服务只记录路径，不读写其配置）。
    """

    data_dir: Path
    host: str
    port: int
    hermes_home: Path


def _default_hermes_home() -> Path:
    """HERMES_HOME 默认值：Windows 为 %LOCALAPPDATA%\\hermes，其他平台为 ~/.hermes。"""
    if sys.platform == "win32":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "hermes"
    return Path.home() / ".hermes"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """读取环境变量并返回进程级缓存的 Settings。

    可通过环境变量覆盖：MASHIRU_DATA_DIR（数据目录）、MASHIRU_HOST（监听地址）、
    MASHIRU_PORT（监听端口）、HERMES_HOME（Hermes 宿主目录）。
    测试在设置环境变量后调用 get_settings.cache_clear()，即可让下一次调用
    按新值重建配置。
    """
    return Settings(
        data_dir=Path(os.environ.get("MASHIRU_DATA_DIR", str(DEFAULT_DATA_DIR))),
        host=os.environ.get("MASHIRU_HOST", "0.0.0.0"),
        port=int(os.environ.get("MASHIRU_PORT", "8123")),
        hermes_home=Path(os.environ.get("HERMES_HOME", str(_default_hermes_home()))),
    )
