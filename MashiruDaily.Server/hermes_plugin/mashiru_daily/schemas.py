"""Hermes 插件工具 Schema：这些描述是 LLM 判断何时调用工具的依据。

所有工具都围绕 MashiruDaily.Server 的 data/todo.json 与 data/todo-meta.json：
- todo.json：PascalCase 待办数组，是服务器侧唯一数据源；
- todo-meta.json：侧车文件，createdAt 只能由 todo_meta_stamp 工具（或等价脚本）
  刷新，webhook 驱动的修改不得触碰。
- 已有条目时可传入已存在的 Id 用于定位。
"""

TODO_LIST = {
    "name": "todo_list",
    "description": "读取 MashiruDaily 服务器端的 data/todo.json，返回全部待办列表。文件缺失时返回空列表。",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

TODO_GET = {
    "name": "todo_get",
    "description": "按 Id 从 data/todo.json 中读取一条待办；不存在时返回 success=false。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "待办 Id（GUID 字符串）"},
        },
        "required": ["id"],
    },
}

TODO_SAVE = {
    "name": "todo_save",
    "description": "整体覆盖写入 data/todo.json。",
    "parameters": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "description": "待办标题数组，仅传标题",
                "items": {"type": "string"},
            },
        },
        "required": ["items"],
        "additionalProperties": False,
    },
}

TODO_UPSERT = {
    "name": "todo_upsert",
    "description": "按 Id 更新已有待办的标题；未传 Id 或 Id 为空时新增一条待办。",
    "parameters": {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "待办标题"},
            "id": {
                "type": "string",
                "description": "已存在待办的 Id（GUID）；省略或为空时表示新增",
            },
        },
        "required": ["title"],
        "additionalProperties": False,
    },
}

TODO_COMPLETED = {
    "name": "todo_completed",
    "description": "修改已有待办的完成状态。接收已存在的 Id（GUID）和 completed 布尔值。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "已存在待办的 Id（GUID）"},
            "completed": {"type": "boolean", "description": "是否已完成"},
        },
        "required": ["id", "completed"],
        "additionalProperties": False,
    },
}

TODO_DELETE = {
    "name": "todo_delete",
    "description": "按 Id 从 data/todo.json 中删除一条待办；不存在时返回 success=false。",
    "parameters": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "description": "待办 Id（GUID 字符串）"},
        },
        "required": ["id"],
    },
}

TODO_META_GET = {
    "name": "todo_meta_get",
    "description": "读取 data/todo-meta.json 元数据（date/createdAt/count）。",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

TODO_META_STAMP = {
    "name": "todo_meta_stamp",
    "description": "刷新 data/todo-meta.json：更新 date 为今日、createdAt 为当前 UTC、count 为实时条数。仅在每日例行维护结束时调用。",
    "parameters": {
        "type": "object",
        "properties": {},
    },
}

# 统一注册表：name -> schema
TOOLS = {
    TODO_LIST["name"]: TODO_LIST,
    TODO_GET["name"]: TODO_GET,
    TODO_SAVE["name"]: TODO_SAVE,
    TODO_UPSERT["name"]: TODO_UPSERT,
    TODO_COMPLETED["name"]: TODO_COMPLETED,
    TODO_DELETE["name"]: TODO_DELETE,
    TODO_META_GET["name"]: TODO_META_GET,
    TODO_META_STAMP["name"]: TODO_META_STAMP,
}
