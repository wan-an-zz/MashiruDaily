"""MashiruDaily Hermes 插件注册入口。
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
