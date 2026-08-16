"""将 MashiruDaily 的 Hermes 插件注册到本机 Hermes（幂等）。

- 把项目内 `hermes_plugin/mashiru_daily/` 以目录链接（Windows junction / POSIX symlink）
  安装到 `$HERMES_HOME/plugins/mashiru-daily`，插件内的 `register(ctx)`
  会通过 Hermes 接口注册全部 `todo_*` 工具与内置 skill；
- 通过 `hermes plugins enable mashiru-daily` 启用插件（Hermes 接口；
  找不到 hermes 可执行文件时回退为直接写 config.yaml 的 plugins.enabled）；
- 把 `hermes_plugin/mashiru_daily/skills` 加入 `skills.external_dirs`，使普通技能名
  `mashiru-todo` 可被 cron / webhook 的 `--skill` 直接使用；同时迁移移除旧
  `Server/skills` 目录引用（若存在）。

需 ruamel.yaml（由 setup_server.py 安装）。用法：
    .venv\\Scripts\\python.exe register_skills.py
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import _config  # 本目录共享的 Hermes 配置工具

# Hermes 插件名与项目内插件源目录（相对 Server 根目录）
PLUGIN_NAME = "mashiru-daily"
PLUGIN_SOURCE_DIR = "hermes_plugin/mashiru_daily"
# 旧的 skills 目录路径（迁移时从 external_dirs 移除）
LEGACY_SKILLS_DIR = "skills"


def _ensure_plugin_linked(server_root: Path, plugin_name: str) -> bool:
    """把 hermes_plugin/mashiru_daily 链接到 HERMES_HOME/plugins/<plugin_name>（幂等）。"""
    hermes_home = _config.get_hermes_home()
    plugins_dir = hermes_home / "plugins"
    plugins_dir.mkdir(parents=True, exist_ok=True)

    source = server_root / PLUGIN_SOURCE_DIR
    target = plugins_dir / plugin_name

    if not source.is_dir():
        print(f"错误：未找到插件源目录 {source}。", file=sys.stderr)
        return False

    # 已存在：若是指向当前源目录的链接则跳过；否则不覆盖，避免破坏用户已有目录
    if target.exists() or target.is_symlink():
        try:
            if target.resolve() == source.resolve():
                print(f"[SKIP] Hermes 插件 {plugin_name} 已链接到 {source}，无需修改。")
                return True
        except OSError:
            pass
        print(
            f"[WARN] {target} 已存在且不是指向 {source} 的链接，跳过安装。"
            "如需重新安装请先手动移除该目录。",
            file=sys.stderr,
        )
        return False

    try:
        if os.name == "nt":
            # Windows 下用 mklink /J 创建 junction，不需要管理员权限
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(target), str(source)],
                capture_output=True,
                text=True,
                errors="replace",
                timeout=30,
            )
            if result.returncode != 0:
                raise OSError((result.stderr or result.stdout or "").strip() or "mklink 失败")
        else:
            target.symlink_to(source, target_is_directory=True)
        print(f"[OK] Hermes 插件 {plugin_name} 已安装（链接 -> {source}）。")
        return True
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"[FAIL] 无法创建插件链接 {target} -> {source}: {exc}", file=sys.stderr)
        return False


def _enable_plugin_via_cli(plugin_name: str) -> bool:
    """优先用 Hermes CLI 启用插件；返回 True 表示 CLI 已成功处理。"""
    hermes = _config.find_hermes_exe()
    if hermes is None:
        return False
    print(f"运行: {subprocess.list2cmdline([hermes, 'plugins', 'enable', plugin_name])}")
    try:
        result = _config.run_command([hermes, "plugins", "enable", plugin_name], timeout=60)
    except TimeoutError:
        print("错误：hermes plugins enable 超时。", file=sys.stderr)
        return False
    if result.returncode != 0:
        print("警告：hermes plugins enable 执行失败，将回退为直接修改 config.yaml。", file=sys.stderr)
        print((result.stderr or result.stdout or "").strip(), file=sys.stderr)
        return False
    if result.stdout.strip():
        print(result.stdout.strip())
    print(f"[OK] Hermes 插件 {plugin_name} 已启用。")
    return True


def _enable_plugin_in_config(yaml_obj, config_path: Path, plugin_name: str) -> bool:
    """回退方案：直接把插件名合并进 config.yaml 的 plugins.enabled。"""
    data = _config.load_config(yaml_obj, config_path)
    if not isinstance(data, dict):
        print("错误：config.yaml 根节点不是映射结构，无法启用插件。", file=sys.stderr)
        return False

    plugins = data.get("plugins")
    if plugins is None:
        plugins = {}
        data["plugins"] = plugins
    if not isinstance(plugins, dict):
        print("错误：config.yaml 中 plugins 不是映射结构，无法启用插件。", file=sys.stderr)
        return False

    enabled = plugins.get("enabled")
    changed = False
    if enabled is None:
        plugins["enabled"] = [plugin_name]
        changed = True
    elif isinstance(enabled, list):
        normalized = {str(item) for item in enabled}
        if plugin_name not in normalized:
            enabled.append(plugin_name)
            changed = True
    else:
        print("错误：config.yaml 中 plugins.enabled 不是列表，无法启用插件。", file=sys.stderr)
        return False

    if not changed:
        print(f"[SKIP] plugins.enabled 已包含 {plugin_name}，无需修改。")
        return True

    backup_path = _config.backup_config(config_path)
    print(f"[OK] 修改前已备份原配置到 {backup_path}")
    _config.dump_config(yaml_obj, data, config_path)
    print(f"[OK] 已在 config.yaml 中启用插件 {plugin_name}。")
    return True


def _sync_external_dirs(yaml_obj, config_path: Path, server_root: Path) -> int:
    """确保 skills.external_dirs 包含 hermes_plugin/skills，并迁移移除旧 skills 目录。"""
    data = _config.load_config(yaml_obj, config_path)
    if not isinstance(data, dict):
        print("错误：config.yaml 根节点不是映射结构，无法修改。请人工检查配置。", file=sys.stderr)
        return 1

    # 新目标：hermes_plugin/mashiru_daily/skills
    new_skills_dir = _config.forward_slashes(server_root / PLUGIN_SOURCE_DIR / "skills")
    # 旧目标：Server/skills（迁移清理）
    legacy_skills_dir = _config.forward_slashes(server_root / LEGACY_SKILLS_DIR)

    if "skills" not in data or data["skills"] is None:
        data["skills"] = {}
    skills = data["skills"]
    if not isinstance(skills, dict):
        print("错误：config.yaml 中 skills 不是映射结构，无法写入 external_dirs。请人工检查配置。", file=sys.stderr)
        return 1

    external_dirs = skills.get("external_dirs")
    changed = False
    if external_dirs is None:
        skills["external_dirs"] = [new_skills_dir]
        changed = True
    elif isinstance(external_dirs, str):
        # 配置异常：单字符串而非列表，重置为列表并保留原值
        skills["external_dirs"] = [external_dirs.replace("\\", "/"), new_skills_dir]
        changed = True
    else:
        normalized = {str(d).replace("\\", "/") for d in external_dirs}
        if new_skills_dir not in normalized:
            external_dirs.append(new_skills_dir)
            changed = True
        # 迁移：移除旧的 Server/skills 引用，避免同名技能冲突
        if legacy_skills_dir in normalized:
            external_dirs[:] = [
                d for d in external_dirs if str(d).replace("\\", "/") != legacy_skills_dir
            ]
            changed = True

    if not changed:
        print(f"[SKIP] skills.external_dirs 已包含 {new_skills_dir}，无需修改。")
    else:
        backup_path = _config.backup_config(config_path)
        print(f"[OK] 修改前已备份原配置到 {backup_path}")
        _config.dump_config(yaml_obj, data, config_path)
        print(f"[OK] 已更新 {config_path}")

        # 重新加载校验
        reloaded = _config.load_config(yaml_obj, config_path)
        final_dirs = reloaded.get("skills", {}).get("external_dirs") or []
        final_normalized = {str(d).replace("\\", "/") for d in final_dirs}
        if new_skills_dir not in final_normalized:
            print("错误：写入后校验失败，skills.external_dirs 中未找到目标路径。", file=sys.stderr)
            return 1
        print("[OK] 写入校验通过。")

    print("\n当前 skills.external_dirs：")
    final_dirs = data["skills"].get("external_dirs") or []
    for d in final_dirs:
        print(f"  - {d}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="将 MashiruDaily 的 Hermes 插件注册到 Hermes（工具/技能，幂等）"
    )
    parser.parse_args()

    yaml_obj = _config.new_yaml()  # 内部已确保 ruamel.yaml 可用
    config_path = _config.get_config_path()
    if not config_path.is_file():
        print(f"错误：未找到配置文件 {config_path}。", file=sys.stderr)
        print("请确认 Hermes Agent 已安装，或设置环境变量 HERMES_HOME 指向其主目录。", file=sys.stderr)
        return 1

    server_root = Path(__file__).resolve().parent

    # 1. 安装/链接插件
    if not _ensure_plugin_linked(server_root, PLUGIN_NAME):
        return 1

    # 2. 启用插件：优先 Hermes CLI，失败回退 config.yaml
    if not _enable_plugin_via_cli(PLUGIN_NAME):
        if not _enable_plugin_in_config(yaml_obj, config_path, PLUGIN_NAME):
            return 1

    # 3. 同步外部 skill 目录（保留普通技能名 mashiru-todo）
    return _sync_external_dirs(yaml_obj, config_path, server_root)


if __name__ == "__main__":
    sys.exit(main())
