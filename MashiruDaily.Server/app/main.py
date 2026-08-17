"""MashiruDaily 拉取服务器：向 C# 客户端暴露 GET /api/todo/meta、GET /api/todo 与 /health。

契约来源：docs/design/通信协议.md §5。字段名须与 C# 端 System.Text.Json
（大小写敏感 snake_case）逐字节对齐；客户端启动时先拉 meta 比对 created_at，
再拉全量列表整体替换本地数据——因此任何额外的键（如本地字段 has_synced）都不得出现。
"""

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.todo_store import current_meta, load_todo_list

app = FastAPI()


@app.exception_handler(ValueError)
async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
    """todo.json / todo-meta.json 非法时由 store 抛 ValueError，统一映射为 HTTP 500。"""
    return JSONResponse(status_code=500, content={"detail": str(exc)})


@app.get("/api/todo/meta")
def get_meta() -> dict:
    """返回元数据：date / created_at 透传侧车，count 取 todo.json 实时长度。"""
    return current_meta()


@app.get("/api/todo")
def get_todo_list() -> list:
    """返回 todo.json 全量列表，snake_case 逐字透传（不含 has_synced）；缺失时返回空数组。"""
    return load_todo_list()


@app.get("/health")
def health() -> dict:
    """健康检查（拉取服务器自身；Hermes Webhook 网关另有 8644 端口上的 /health）。"""
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=get_settings().host, port=get_settings().port)
