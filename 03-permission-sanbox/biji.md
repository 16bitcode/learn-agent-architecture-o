permission层必须做到：

1. 在每个工具调用执行前先查看它
2. 决定allow、ask、deny
3. 当高风险的调用尚未批准时，询问用户
4. 当调用真的执行时，限制它造成的伤害

核心机制

1. 工具调用请求 tool_use
   模型提出请求
   此时尚未执行任何操作
2. 权限决策 decide()
   一个纯函数，返回三种结果之一：允许allow、询问ask、拒绝deny
   决策依据包括"运行模式与允许规则":
   规划模式plan禁止编辑
   绕过模式bypass跳过权限关卡
3. 根据决策进入不同路径
   允许allow -> 执行工具
   询问ask -> 进入用户是否批准
   默认不批准
   yes -> 执行工具
   no -> 返回用户拒绝的结果
4. 执行工具 Run tool
   在这一步产生副作用
   尽可能在沙箱中执行
5. 工具结果 tool_result
   即使调用被拒绝，也必须返回结果
   拒绝信息本身也是一种结果

一个纯函数负责做出 permission 决策。它读取工具、目前的mode、所有allow的规则，并返回allow、ask、deny
mode 会改变默认行为。比如 plan mode允许只读工具，但在计划批准前拒绝编辑

decide() 就是整个 permission 决策

如何集成到现有架构
gate 在 \_dispatch 内部执行，就在run_tool之前
