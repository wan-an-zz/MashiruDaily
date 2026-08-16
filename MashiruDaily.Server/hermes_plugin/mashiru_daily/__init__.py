"""MashiruDaily Hermes 插件注册入口。

通过 Hermes 插件接口完成：
- tool 注册：ctx.register_tool() 将 todo.json / todo-meta.json 的读写全部包装为工具；
- skill 注册：ctx.register_skill() 将 skills/mashiru-todo 注册为插件命名空间技能
  （mashiru-daily:mashiru-todo），同时 register_skills.py 也会把该目录加入
  skills.external_dirs，保留普通技能名 mashiru-todo 供 cron/webhook 直接使用。
"""

from pathlib import Path

from . import schemas, tools


def register(ctx) -> None:
    """Hermes 插件入口：注册全部工具与内置技能。"""
    for name, schema in schemas.TOOLS.items():
        handler = getattr(tools, name)
        ctx.register_tool(
            name=name,
            toolset="mashiru_daily",
            schema=schema,
            handler=handler,
            description=schema.get("description", ""),
        )

    skills_dir = Path(__file__).resolve().parent / "skills"
    for child in sorted(skills_dir.iterdir()):
        skill_md = child / "SKILL.md"
        if child.is_dir() and skill_md.exists():
            ctx.register_skill(child.name, skill_md)
