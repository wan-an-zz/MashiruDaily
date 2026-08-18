"""Hermes 配置共享工具（纯标准库）：路径解析、config.yaml 读写与备份、hermes 可执行文件定位。

供 register_hermes_plugin.py / configure_webhook.py / configure_cron.py 复用：
- config.yaml 一律使用 ruamel.yaml 的 round-trip 模式读写，保留注释与格式；
- 修改前按 config.yaml.bak-<时间戳> 规则备份，且仅在真正需要修改时备份。
"""

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def get_hermes_home() -> Path:
    """返回 Hermes 主目录：环境变量 HERMES_HOME 优先，否则 %LOCALAPPDATA%\\hermes。"""
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).resolve()
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "hermes"
    # 兜底：既无 HERMES_HOME 也无 LOCALAPPDATA 时，退到家目录下的 .hermes
    return Path.home() / ".hermes"


def get_config_path() -> Path:
    """返回 HERMES_HOME/config.yaml 的完整路径。"""
    return get_hermes_home() / "config.yaml"


def require_ruamel():
    """导入 ruamel.yaml；不可用时打印清晰提示并以退出码 1 结束。"""
    try:
        import ruamel.yaml
        return ruamel.yaml
    except ImportError:
        print("错误：未找到 ruamel.yaml 模块。", file=sys.stderr)
        print("请先运行 setup_server.py 创建虚拟环境并安装 requirements.txt 依赖，", file=sys.stderr)
        print("再用 .venv\\Scripts\\python.exe 重新运行本脚本。", file=sys.stderr)
        sys.exit(1)


def new_yaml():
    """创建 ruamel round-trip 模式的 YAML 实例（保留注释与引号，不折行）。"""
    ruamel_yaml = require_ruamel()
    yaml_obj = ruamel_yaml.YAML()
    yaml_obj.preserve_quotes = True
    yaml_obj.width = 4096
    return yaml_obj


def load_config(yaml_obj, path: Path):
    """以 round-trip 模式读取 YAML 文件，返回可原地修改的数据。"""
    with open(path, "r", encoding="utf-8") as f:
        return yaml_obj.load(f)


def dump_config(yaml_obj, data, path: Path) -> None:
    """以 round-trip 模式写回 YAML 文件。"""
    with open(path, "w", encoding="utf-8") as f:
        yaml_obj.dump(data, f)


def backup_config(path: Path) -> Path:
    """备份配置文件为 <name>.bak-<YYYYmmddHHMMSS>，返回备份路径。

    时间戳精度到秒：同一秒内连续多次备份（如卸载流程中 webhook 与插件两步同秒
    修改 config.yaml）会冲突，冲突时追加 -N 后缀保证不覆盖前一份备份。
    """
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = path.with_name(f"{path.name}.bak-{ts}")
    suffix = 1
    while backup_path.exists():
        backup_path = path.with_name(f"{path.name}.bak-{ts}-{suffix}")
        suffix += 1
    shutil.copy2(path, backup_path)
    return backup_path


def forward_slashes(p) -> str:
    """将路径统一为正斜杠形式，写入 YAML 时无需额外转义。"""
    return Path(p).as_posix()


def find_hermes_exe():
    """定位 hermes 可执行文件（跨平台）：
    1. <HERMES_HOME>\\hermes-agent\\venv\\Scripts\\hermes.exe（Windows）或
       <HERMES_HOME>/hermes-agent/venv/bin/hermes（Linux/macOS，HERMES_HOME 可用环境变量覆盖）；
    2. PATH 上的 hermes 命令。
    返回可执行文件路径；均未找到时返回 None。
    """
    venv_dir = get_hermes_home() / "hermes-agent" / "venv"
    candidate = (
        venv_dir / "Scripts" / "hermes.exe"
        if os.name == "nt"
        else venv_dir / "bin" / "hermes"
    )
    if candidate.is_file():
        return str(candidate)
    which = shutil.which("hermes")
    if which:
        return which
    return None


def run_command(cmd, timeout=120):
    """运行子进程并捕获输出：按文本解码，非法字节以替换符容错，避免中文输出导致崩溃。"""
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        errors="replace",
        timeout=timeout,
    )
