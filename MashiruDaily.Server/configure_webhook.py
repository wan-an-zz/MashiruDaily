"""配置 Hermes 的 webhook 平台与 todo-sync 路由（幂等）。

- 合并 platforms.webhook = {enabled, extra:{port, routes:{todo-sync:{...}}}}，
  其它平台（如 qqbot）与既有路由一律保留；
- todo-sync 路由通过 `toolsets: ["mashiru_daily"]` 声明 Hermes 可调用的插件工具集；
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

# 良性降级信号：Hermes 源码（NousResearch/hermes-agent hermes_cli/gateway.py
# _system_service_identity）在以 root 运行且网关为 systemd 系统服务时，拒绝刷新
# systemd 单元并抛未捕获的 ValueError（裸 traceback 进 stderr，退出码 1）；root 下
# 用户级 D-Bus 不可达时由 print_error 输出（写 stdout）。两者都是 config.yaml 已
# 成功写入、仅重启动作受限的场景，应降级为提示而非失败。注意两个信号可能落在
# 不同输出流，匹配时必须合并 stdout 与 stderr。
_ROOT_REFUSAL_SIGNAL = "Refusing to install the gateway system service as root"
_USER_SYSTEMD_UNAVAILABLE_SIGNAL = "User systemd not reachable"

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
        and list(todo_sync.get("toolsets") or []) == desired["toolsets"]
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

def _data_dir() -> Path:
    """返回数据目录：优先环境变量 MASHIRU_DATA_DIR，否则 $HOME/.mashiru-daily/todos。"""
    env = os.environ.get("MASHIRU_DATA_DIR")
    if env:
        return Path(env)
    return Path.home() / ".mashiru-daily" / "plans"


def main(argv: list[str] | None = None) -> int:
    """解析参数并按序执行：校验密钥 → 合并 webhook 配置 → 写回校验 → 重启网关。"""
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
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    # 密钥来源：--secret 参数优先，其次环境变量；两者皆无则拒绝运行
    secret = (args.secret or os.environ.get("MASHIRU_WEBHOOK_SECRET") or "").strip()
    if not secret:
        print("错误：缺少 webhook 密钥。", file=sys.stderr)
        print("请通过 --secret <密钥> 或修改环境变量 MASHIRU_WEBHOOK_SECRET 提供", file=sys.stderr)
        return 1

    yaml_obj = _config.new_yaml()  # 内部已确保 ruamel.yaml 可用
    config_path = _config.get_config_path()
    if not config_path.is_file():
        print(f"错误：未找到配置文件 {config_path}。", file=sys.stderr)
        print("请确认 Hermes Agent 已安装，或设置环境变量 HERMES_HOME 指向其主目录。", file=sys.stderr)
        return 1

    # 构造 todo-sync 路由
    prompt_text = (
        f"你帮助用户制定了高考提升的每日计划，现在用户对某些待办产生了修改(包括但不限于完成、修改内容或删除等等)。你帮助用户制定的计划在{_data_dir()}目录下。假设你需要阅读当前用户手中已被修改的计划，请调用TODO_LIST工具。现在你需要根据用户对待办产生的修改，调用SPEAK_TO_USER工具给出回应(可以是鼓励用户或询问用户之类的)。你禁止修改包括计划和待办在内的任何内容，你禁止直接访问todo.json和todo-meta.json，只允许使用工具进行访问。以下是被修改的待办的内容：{{__raw__}}"
    )
    desired_todo_sync = {
        "events": ["update"],
        "secret": secret,
        "prompt": _literal_scalar(prompt_text),
        "toolsets": ["mashiru_daily"],
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

    # 重启网关
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
    return _restart_gateway(hermes)


def _restart_gateway(hermes: str) -> int:
    """执行 hermes gateway restart；遇 Hermes 的良性拒绝场景时降级为提示并返回 0。

    返回 0 的降级场景（config.yaml 已写入成功，仅重启未执行）：
    - root 下 Hermes 拒绝刷新 systemd 系统服务单元（_system_service_identity 抛
      ValueError，裸 traceback 进 stderr）；
    - root 下用户级 systemd D-Bus 不可达（"User systemd not reachable" 进 stdout）。
    其余失败（超时 / 无关错误）保持返回 1，不掩盖真实问题。
    """
    print("\n正在重启 Hermes 网关（webhook 连接将短暂断开）...")
    try:
        result = _config.run_command([hermes, "gateway", "restart"], timeout=120)
    except TimeoutError:  # subprocess.TimeoutExpired 是 TimeoutError 的子类
        print("错误：网关重启超时。", file=sys.stderr)
        return 1
    if result.returncode == 0:
        print("[OK] 网关重启成功，webhook 配置已生效。")
        return 0

    # 两个信号可能落在不同输出流，必须合并匹配（Hermes 拒绝消息经未捕获
    # ValueError 的 traceback 进 stderr；"User systemd not reachable" 由
    # print_error 写 stdout）。
    combined = (result.stderr or "") + (result.stdout or "")
    if _ROOT_REFUSAL_SIGNAL in combined or _USER_SYSTEMD_UNAVAILABLE_SIGNAL in combined:
        print("[WARN] Hermes 拒绝在 root 下重启网关，webhook 配置已写入 config.yaml，")
        print("将在 Hermes 下次重启时生效。本次未执行重启；可手动重启或等待下次重启。")
        if _ROOT_REFUSAL_SIGNAL in combined:
            print("修复建议：运行 `sudo hermes gateway restart`，")
            print("或 `sudo systemctl restart hermes-gateway.service`。")
            if combined.strip():
                print("\nHermes 输出：")
                print(combined.strip())
            return 2
        else:
            print("修复建议：以 Hermes 所属用户执行 `hermes gateway restart`")
            print("（若未登录先 `sudo loginctl enable-linger <用户>`）或 `hermes gateway run`。")
            if combined.strip():
                print("\nHermes 输出：")
                print(combined.strip())
            return 3
        

    print("警告：网关重启命令返回非零退出码。", file=sys.stderr)
    print(combined.strip(), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
