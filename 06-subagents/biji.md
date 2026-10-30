主agent可以把工作交给subagent。负责委派的一方叫parent，接下任务的一方叫child

对parent来说，委派开起来只是一个tool call，但工具内部起始会启动完整的agent loop。

parent传入prompt，child使用全新的messages[]执行任务，完成后只返回最终答案。

这样做能让旁支调查不进到parent的context。parent不需要看到child读过的每个文件和每段命令输出，通常只需要最后的结论。

没有subagent，所有调查过程都会堆在主transcript中。跑的越久，过程就越杂乱、成本越高，模型也更难跟上。

Agent tool 会启动一个child agent。child拥有子集的session和message列表，但执行的仍是和parent相同的loop。
返回给parent的只有child最后输出的文字，child的transcript不会一起返回。文件写入和shell副作用仍然会发生在工作目录。

```python
def agent_tool(model, child_registry, parent_session):
    def spawn(a):
        child = Session(mode=parent_session.mode, allow_rules=set(parent_session.allow_rules))
        messages = [{'role': 'user', 'content': a['description']}]
        return run_turn(messages, model, child_registry, child)
    return Tool('Agent', spawn, is_read_only=True)
```

- agent_tool 返回一个一般的tool
- 它的handler用一个新的Session调用run_turn
- child的messages[]一开始只有child的prompt
- child返回run_turn()所返回的文字

如何集成到现有架构

loop不会改变。subagent 只是另一个调用loop的tool handler
有三个特性很重要：

- 全新context: child不会继承parent的transcript。parent也不会继承child的轨迹。
- 继承的权限：child会复制parent的permission mode和allow rules。context隔离不等于权限隔离。
- 递归上限：这个demo从child registry中省略了Agent，所以child无法再生出另一个child。
