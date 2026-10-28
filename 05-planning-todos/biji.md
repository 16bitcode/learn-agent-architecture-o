大型任务需要一份明确、可追踪的计划。如果计划只存在prompt中，经过多轮工具调用后，模型很容易忘记原本的进度。

规划解决了2个各自独立的问题：

1. agent工作时需要一份随时可更新的检查列表
2. agent还没理解任务前，不应该直接修改文件

todo工具保存检查列表
plan mode则把agent限制在只读探索，直到计划通过批准

在计划获得批准前，计划模式会阻止编辑。TodoWrite用于持续更新待办清单。

1. 复杂任务：需要分多步完成
2. 先制定计划吗？是否需要在编辑前先探索？
   1. 是 -> 进入计划模式(EnterPlanMode) -> 探索并编写计划（只能使用只读工具，不能编辑）-> 退出计划模式(ExitPlanMode)，请求批准计划
   2. 否 -> 直接列出步骤
3. 计划获得批准后 -> 用TodoWrite写入待办清单（会覆盖原清单，仅在当前会话中保存）
4. 逐项完成清单：将事项标为in_progress（进行中）-> 执行 -> 标为completed（已完成），然后处理下一个待办事项

这里有2个工具。两个都是一般的模型工具，核心loop完全不需要修改。

Todo list。模型会覆盖一份结构化的检查列表。这个工具不会碰文件或shell，只负责保存目前session的计划状态。
Plan mode。session进入只读模式。模型可以探索、写下计划，然后调用ExitPlanMode。这个离开动作由permission层把关。

```python
@dataclass
class Session:
    mode: str = DEFAULT
    todos: list = field(default_factory=list)

def todo_tool(session):
    def write(a): session.todos = list(a['todos'])
    return Tool('TodoWrite', write, is_read_only=True)

def exit_plan_mode_tool(session):
    def exit_plan(): session.mode = ACCEPT_EDITS
    return Tool('ExitPlanMode', exit_plan)
```

- Session 现在只存放mode和todos
- TodoWrite 只改动session.todos，所以从外部看它是只读的
- ExitPlanMode 在批准后改变 session.mode
- 下一次工具调用会通过同一个 permission gate 读到新的 mode

第三章的 permission 逻辑已经认得 PLAN

```python
if mode == PLAN:
    if tool.is_read_only: return 'allow'
    if tool.name == 'ExitPlanMode': return 'ask'
    return 'deny'
```

本章加入的是工具和session状态。并没有加入新的loop或新的permission路径

一个todo项目是 {content, status, activeForm}
status的状态有pending、in_progress、completed。模型每次都会写入整份列表，而harness负责把目前状态渲染出来。
