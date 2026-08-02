# Todo JSON 持久化设计

日期：2026-08-02
分支：feature/TODO列表

## 背景

TODO 数据目前仅存于内存（`InMemoryTodoRepository`），进程结束后丢失。需要将数据持久化到 `SpecialFolder.ApplicationData` 下的 JSON 文件，每次对 Todo 的操作（增、删、改、切换完成状态）都触发一次保存，并且持久化逻辑要单独封装、降低耦合。

## 目标与非目标

**目标**
- Todo 数据在应用重启后仍保留。
- 每次变更即保存，无需手动触发。
- 持久化细节封装在仓储层，业务层（`TodoService`）只依赖 `ITodoRepository` 接口，不感知文件路径/序列化。

**非目标**
- 不引入数据库或第三方序列化库（`System.Text.Json` 已满足，net10.0 自带）。
- 不做自动保存合并/防抖——当前数据量小，每次操作全量写文件成本可接受。
- 不改动 `ITodoRepository` 接口签名。

## 方案选择

选定：**JsonTodoRepository + 服务端触发保存**。

- 复用现有 `ITodoRepository`（`LoadAsync`/`SaveAsync`）抽象，新建 `JsonTodoRepository` 作为其文件实现。
- `TodoService` 每次变更后调用 `SaveAsync`。
- 旧 `InMemoryTodoRepository` 保留，供测试与无文件场景使用。

备选（已否决）：
- 仓储内部 write-through 自动落盘——仓储反向依赖服务，耦合升高。
- AutoSave 装饰器——现有接口是"全量保存"、无变更粒度，无法自然触发，需新增方法，过度设计。

## 架构

```
TodoPageViewModel ──> ITodoService ──> ITodoRepository (JsonTodoRepository)
                                          │
                                          └──> %APPDATA%\MashiruDaily\todos.json
```

分层保持现状：`ViewModels` → `Abstracts`（接口）→ `Services`（实现）。`JsonTodoRepository` 与 `TodoService` 同属 `Services` 命名空间，与既有 `InMemoryTodoRepository` 并列。

## 组件设计

### JsonTodoRepository（新增，`Services/JsonTodoRepository.cs`）

实现 `ITodoRepository`，负责 JSON 文件读写：

- **文件路径**：`Path.Combine(Environment.GetFolderPath(SpecialFolder.ApplicationData), "MashiruDaily", "todos.json")`。
- **LoadAsync**：
  - 文件不存在 → 返回空列表。
  - 文件损坏/反序列化失败 → 记录错误日志（NLog），返回空列表，不向调用方抛异常。
- **SaveAsync**：
  - 目录不存在时自动创建（`Directory.CreateDirectory`）。
  - 用 `JsonSerializer.Serialize` 写入列表；`WriteIndented = true` 便于人工排查。
  - 写入失败 → 记录错误日志，不向调用方抛异常（避免 UI 操作因磁盘问题中断）。
- **序列化兼容性**：`TodoItem` 的 `Id`/`CreatedAt` 为 `init` setter，`System.Text.Json` 可正常反序列化，无需调整模型。

### TodoService（修改，`Services/TodoService.cs`）

- 构造函数不再阻塞加载数据；改为提供 `InitializeAsync()`，首次异步加载列表。
- `AddAsync` / `RemoveAsync` / `ToggleAsync` / `UpdateTitleAsync` 末尾 `await _repository.SaveAsync(_items)`。
- `Changed` 事件语义不变。

### App 启动（修改，`App.axaml.cs`）

- `OnFrameworkInitializationCompleted` 中在创建主窗口/主视图前 `await TodoService.InitializeAsync()`。
- DI 注册：`ITodoRepository` 从 `InMemoryTodoRepository` 改为 `JsonTodoRepository`。

## 数据流

1. 启动 → `ConfigureServices` 注册 `JsonTodoRepository` → await `TodoService.InitializeAsync()` 读文件填充内存列表 → 创建 UI。
2. 用户操作（添加/删除/改标题/切换）→ `TodoService` 变更内存 → `Changed` 通知 UI 刷新 → `SaveAsync` 全量写 JSON。
3. 重启 → 再次从 JSON 加载。

## 错误处理

- 读：文件缺失视为"首次使用"，空列表；JSON 损坏记录日志，空列表（不崩溃，日志中保留原始异常便于排查）。
- 写：IO 异常记录日志并继续（内存数据仍正确，仅丢失持久化）。
- 初始化异常：加载失败不阻止应用启动。

## 测试

- `TodoService` 变更操作后应调用 `SaveAsync` —— 使用 fake 仓储断言。
- `JsonTodoRepository` 往返测试：保存后再加载，数据一致（Id/Title/IsCompleted/CreatedAt/CompletedAt）。
- 文件不存在时 `LoadAsync` 返回空。
- 损坏的 JSON 返回空且不抛异常。

（项目当前无测试工程；如已有测试基础设施则复用，否则在本轮实现计划中评估是否新增最小测试项目。）

## 明确决策

- 保存时机：每次变更全量写盘，无防抖。
- 文件格式：单 JSON 数组 `[ { "Id": ..., "Title": ..., "IsCompleted": ..., "CreatedAt": ..., "CompletedAt": ... }, ... ]`。
- 序列化库：`System.Text.Json`，不新增 NuGet 包。
- 失败策略：读写失败仅记日志，不抛给 UI。
