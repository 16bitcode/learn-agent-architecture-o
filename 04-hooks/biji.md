hook时可以自行配置的callback，可以在工具调用前后、prompt送出、session开始或结束时执行

记录、验证、通知、简单的策略检查都适合hook

少了hook，每加入一种行为都要修改loop，甚至维护一份分支

hook的价值在于让loop保持精简。loop只需要公开固定的生命周期事件，其他行为再挂到对应事件上。

Hooks

1. 工具调用请求 tool_use
   来自模型的工具名称和输入参数
2. 工具调用前钩子 PreToolUse
   用户自定义钩子可以拦截调用，或改写输入参数
   通过pass -> 进入权限关卡，此时参数可能已被改写
   拒绝deny -> 在权限关卡之前拦截，直接返回工具结果
3. 权限关卡 Permission gate
   使用03的decide()，逻辑保持不变
   允许allow -> 执行工具
   拒绝或未获批准 deny or unapproved -> 直接返回工具结果
4. 执行工具 Run tool
   只有通过前置钩子且获得权限允许的调用，才会执行
5. 工具调用后钩子PostToolUse
   观察执行情况、记录日志、发送通知
   仅在工具执行成功后运行
6. 工具结果 tool_result
   所有路径最终都汇聚到这里
   将结果返回给模型

Hooks 对象会把事件名称对应到一组callback。loop不会直接调用自定义检查，而是由\_dispatch出发命名事件。

在工具执行方面，有2个重要的点：

- PreToolUse 在 permission gate 之前执行。它可以挡下调用，或改写输入
- PostToolUse 在工具调用成功之后执行。它可以观察结果
