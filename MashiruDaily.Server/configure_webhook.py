"""配置 Hermes 的 webhook 平台与 todo-sync 路由（幂等）。

- 合并 platforms.webhook = {enabled, extra:{port, routes:{todo-sync:{...}}}}，
  其它平台（如 qqbot）与既有路由一律保留；
- secret 必须来自 --secret 参数或环境变量 MASHIRU_WEBHOOK_SECRET，绝不硬编码、绝不交互输入；
- 使用 ruamel.yaml round-trip 模式，保留注释；仅在真正修改前备份；
- 修改成功后默认执行 `hermes gateway restart`，可用 --no-restart 跳过并打印命令。

用法：
    .venv\\Scripts\\python.exe configure_webhook.py --secret <密钥>
    .venv\\Scripts\\python.exe configure_webhook.py --secret <密钥> --no-restart
"""

import argparse
import copy
import io
import os
import sys
from pathlib import Path

import _config  # 本目录共享的 Hermes 配置工具

# webhook 监听端口（与 Hermes 官方文档/网关实现保持一致）
WEBHOOK_PORT = 8644

# todo-sync 路由订阅的事件
TODO_SYNC_EVENTS = [
    "todo_added",
    "todo_updated",
    "todo_completed",
    "todo_reopened",
    "todo_deleted",
]


def _literal_scalar(text: str):
    """构造 ruamel 的字面量块标量，使多行 prompt 以 | 块形式写入 YAML（更易读）。"""
    from ruamel.yaml.scalarstring import LiteralScalarString

    return LiteralScalarString(text)


def _webhook_identical(webhook, desired: dict) -> bool:
    """判断现有 webhook 配置与期望配置是否完全一致（幂等判断）。"""
    if not isinstance(webhook, dict):
        return False
    if webhook.get("enabled") is not True:
        return False
    extra = webhook.get("extra")
    if not isinstance(extra, dict) or extra.get("port") != WEBHOOK_PORT:
        return False
    routes = extra.get("routes")
    if not isinstance(routes, dict):
        return False
    todo_sync = routes.get("todo-sync")
    if not isinstance(todo_sync, dict):
        return False
    return (
        list(todo_sync.get("events") or []) == desired["events"]
        and str(todo_sync.get("secret") or "") == desired["secret"]
        and str(todo_sync.get("prompt") or "") == desired["prompt"]
        and list(todo_sync.get("skills") or []) == desired["skills"]
    )


def _redact_secret(webhook) -> dict:
    """深拷贝 webhook 配置块，并把全局与各路由的 secret 掩码为 ***，用于安全打印。

    原 webhook 块来自 config 活数据，直接修改会污染内存中的配置；必须深拷贝。
    """
    masked = copy.deepcopy(webhook)
    extra = masked.get("extra")
    if isinstance(extra, dict) and "secret" in extra:
        extra["secret"] = "***"
    routes = extra.get("routes") if isinstance(extra, dict) else None
    if isinstance(routes, dict):
        for route in routes.values():
            if isinstance(route, dict) and "secret" in route:
                route["secret"] = "***"
    return masked


def _print_webhook_block(webhook) -> None:
    """以 YAML 形式打印当前 platforms.webhook 子块（secret 一律掩码为 ***，防止终端泄漏）。"""
    yaml_obj = _config.new_yaml()
    buf = io.StringIO()
    yaml_obj.dump({"webhook": _redact_secret(webhook)}, buf)
    print(buf.getvalue())


def main() -> int:
    parser = argparse.ArgumentParser(
        description="配置 Hermes 的 webhook 平台与 todo-sync 路由（幂等，需提供密钥）"
    )
    parser.add_argument(
        "--secret",
        help="webhook 密钥（也可通过环境变量 MASHIRU_WEBHOOK_SECRET 提供，二选一必填）",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="修改成功后不执行 hermes gateway restart，仅打印命令",
    )
    args = parser.parse_args()

    # 密钥来源：--secret 参数优先，其次环境变量；两者皆无则拒绝运行
    secret = (args.secret or os.environ.get("MASHIRU_WEBHOOK_SECRET") or "").strip()
    if not secret:
        print("错误：缺少 webhook 密钥。", file=sys.stderr)
        print("请通过 --secret <密钥> 或环境变量 MASHIRU_WEBHOOK_SECRET 提供，禁止硬编码或交互输入。", file=sys.stderr)
        return 1

    yaml_obj = _config.new_yaml()  # 内部已确保 ruamel.yaml 可用
    config_path = _config.get_config_path()
    if not config_path.is_file():
        print(f"错误：未找到配置文件 {config_path}。", file=sys.stderr)
        print("请确认 Hermes Agent 已安装，或设置环境变量 HERMES_HOME 指向其主目录。", file=sys.stderr)
        return 1

    # 构造期望的 todo-sync 路由（prompt 引用服务器数据文件，使用 {__raw__} 模板 token）
    server_root = Path(__file__).resolve().parent
    todo_json = _config.forward_slashes(server_root / "data" / "todo.json")
    plan_md = _config.forward_slashes(server_root / "data" / "plan.md")
    prompt_text = (
        f"收到 Todo 变更事件：\n{{__raw__}}\n\n"
        f"请根据事件更新 {todo_json}（PascalCase 字段 Id/Title/IsCompleted/CreatedAt/CompletedAt，禁止传输 HasSynced）。"
        f"必要时同步 {plan_md}。完成后无需报告。"
    )
    desired_todo_sync = {
        "events": TODO_SYNC_EVENTS,
        "secret": secret,
        "prompt": _literal_scalar(prompt_text),
        "skills": ["mashiru-todo"],
    }

    data = _config.load_config(yaml_obj, config_path)
    if not isinstance(data, dict):
        print("错误：config.yaml 根节点不是映射结构，无法修改。请人工检查配置。", file=sys.stderr)
        return 1

    # platforms：已存在（如 platforms.qqbot）则只合并 webhook，绝不触碰其它平台
    platforms = data.get("platforms")
    if platforms is None:
        platforms = {}
        data["platforms"] = platforms
    if not isinstance(platforms, dict):
        print("错误：config.yaml 中 platforms 不是映射结构，无法合并 webhook。请人工检查配置。", file=sys.stderr)
        return 1

    # 幂等判断：配置已一致则直接打印并退出
    webhook = platforms.get("webhook")
    if _webhook_identical(webhook, desired_todo_sync):
        print("[SKIP] platforms.webhook 配置与期望一致，无需修改。")
        _print_webhook_block(webhook)
        return 0

    # 合并（就地更新；todo-sync 已存在则覆盖为最新配置，其余路由保留）
    if not isinstance(webhook, dict):
        webhook = {}
        platforms["webhook"] = webhook
    webhook["enabled"] = True
    extra = webhook.get("extra")
    if not isinstance(extra, dict):
        extra = {}
        webhook["extra"] = extra
    extra["port"] = WEBHOOK_PORT
    routes = extra.get("routes")
    if not isinstance(routes, dict):
        routes = {}
        extra["routes"] = routes
    routes["todo-sync"] = dict(desired_todo_sync)

    # 备份 + 写回 + 重载校验
    backup_path = _config.backup_config(config_path)
    print(f"[OK] 修改前已备份原配置到 {backup_path}")
    _config.dump_config(yaml_obj, data, config_path)
    print(f"[OK] 已更新 {config_path}")

    reloaded = _config.load_config(yaml_obj, config_path)
    ts = reloaded.get("platforms", {}).get("webhook", {}).get("extra", {}).get("routes", {}).get("todo-sync")
    if not isinstance(ts, dict) or str(ts.get("secret") or "") != secret:
        print("错误：写入后校验失败，todo-sync 路由未正确落盘。", file=sys.stderr)
        return 1
    print("[OK] 写入校验通过。")

    # 打印最终 platforms.webhook 配置
    print("\n当前 platforms.webhook 配置：")
    _print_webhook_block(platforms["webhook"])

    # 重启网关（webhook 变更需重启生效；网关作为计划任务运行，重启会短暂断开连接）
    if args.no_restart:
        hermes = _config.find_hermes_exe()
        restart_cmd = "hermes gateway restart" if hermes is None else f"{hermes} gateway restart"
        print(f"\n未执行网关重启（--no-restart）。可手动执行：")
        print(f"  {restart_cmd}")
        return 0
    hermes = _config.find_hermes_exe()
    if hermes is None:
        print("\n错误：找不到 hermes 可执行文件，无法自动重启网关。", file=sys.stderr)
        print("请手动执行：hermes gateway restart", file=sys.stderr)
        return 1
    print("\n正在重启 Hermes 网关（webhook 连接将短暂断开）...")
    try:
        result = _config.run_command([hermes, "gateway", "restart"], timeout=120)
    except TimeoutError:  # subprocess.TimeoutExpired 是 TimeoutError 的子类
        print("错误：网关重启超时。", file=sys.stderr)
        return 1
    if result.returncode != 0:
        print("警告：网关重启命令返回非零退出码。", file=sys.stderr)
        print(result.stderr.strip() or result.stdout.strip(), file=sys.stderr)
        return 1
    print("[OK] 网关重启成功，webhook 配置已生效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
