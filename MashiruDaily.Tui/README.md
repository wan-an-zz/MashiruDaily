# MashiruDaily TUI

基于 [Terminal.Gui v2](https://github.com/tui-cs/Terminal.Gui) 的 MashiruDaily Todo
终端界面。左侧是 Todo List 导航，右侧显示 Todo 标题以及“待完成”和“已完成”两栏；每行包含
勾选框、标题和删除按钮。

```bash
dotnet run --project MashiruDaily.Tui
dotnet build MashiruDaily.Tui
```

操作：

- `↑` / `↓`：选择当前栏的 Todo
- `Space`：切换完成状态
- `Tab` / `→`：在当前行、删除按钮和另一列表之间循环移动焦点
- `D` / `Delete`：确认并删除当前选中的 Todo；也可直接聚焦删除按钮后回车
- `Esc`：退出并冲刷数据

TUI 与桌面应用共享 Core 后端和 `todos.json` 数据，因此两端看到的是同一份 Todo。
