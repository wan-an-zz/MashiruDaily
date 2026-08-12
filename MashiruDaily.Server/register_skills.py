"""将本项目的 skills 目录注册到 Hermes 的 skills.external_dirs（幂等）。

- 使用 ruamel.yaml 的 round-trip 模式读写 config.yaml，保留原有注释；
- 目标路径以绝对路径 + 正斜杠写入：D:/MashiruDaily/MashiruDaily.Server/skills；
- 仅在真正发生修改前备份 config.yaml（.bak-<时间戳>）；
- 重复运行不产生任何改动，也不产生新备份。

需 ruamel.yaml（由 setup_server.py 安装）。用法：
    .venv\\Scripts\\python.exe register_skills.py
"""

import sys
from pathlib import Path

import _config  # 本目录共享的 Hermes 配置工具


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="将 MashiruDaily.Server/skills 注册到 Hermes 的 skills.external_dirs（幂等）"
    )
    parser.parse_args()

    yaml_obj = _config.new_yaml()  # 内部已确保 ruamel.yaml 可用，缺失时给出友好提示
    config_path = _config.get_config_path()
    if not config_path.is_file():
        print(f"错误：未找到配置文件 {config_path}。", file=sys.stderr)
        print("请确认 Hermes Agent 已安装，或设置环境变量 HERMES_HOME 指向其主目录。", file=sys.stderr)
        return 1

    # 目标 skills 目录：本 Server 根目录下的 skills，绝对路径、正斜杠
    server_root = Path(__file__).resolve().parent
    skills_dir = _config.forward_slashes(server_root / "skills")

    data = _config.load_config(yaml_obj, config_path)
    if not isinstance(data, dict):
        print("错误：config.yaml 根节点不是映射结构，无法修改。请人工检查配置。", file=sys.stderr)
        return 1

    changed = False

    # 确保 skills 键存在
    if "skills" not in data or data["skills"] is None:
        data["skills"] = {}
        changed = True
    skills = data["skills"]
    if not isinstance(skills, dict):
        print("错误：config.yaml 中 skills 不是映射结构，无法写入 external_dirs。请人工检查配置。", file=sys.stderr)
        return 1

    # 确保 skills.external_dirs 存在并包含目标路径（规范化后去重）
    external_dirs = skills.get("external_dirs")
    if external_dirs is None:
        skills["external_dirs"] = [skills_dir]
        changed = True
    elif isinstance(external_dirs, str):
        # 配置异常：单字符串而非列表，重置为列表并保留原值
        skills["external_dirs"] = [external_dirs.replace("\\", "/"), skills_dir]
        changed = True
    else:
        normalized = {str(d).replace("\\", "/") for d in external_dirs}
        if skills_dir not in normalized:
            external_dirs.append(skills_dir)
            changed = True

    if not changed:
        print(f"[SKIP] skills.external_dirs 已包含 {skills_dir}，无需修改。")
    else:
        backup_path = _config.backup_config(config_path)
        print(f"[OK] 修改前已备份原配置到 {backup_path}")
        _config.dump_config(yaml_obj, data, config_path)
        print(f"[OK] 已更新 {config_path}")

        # 重新加载校验
        reloaded = _config.load_config(yaml_obj, config_path)
        final_dirs = reloaded.get("skills", {}).get("external_dirs") or []
        final_normalized = {str(d).replace("\\", "/") for d in final_dirs}
        if skills_dir not in final_normalized:
            print("错误：写入后校验失败，skills.external_dirs 中未找到目标路径。", file=sys.stderr)
            return 1
        print("[OK] 写入校验通过。")

    # 打印最终状态
    print("\n当前 skills.external_dirs：")
    final_dirs = data["skills"].get("external_dirs") or []
    for d in final_dirs:
        print(f"  - {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
