用户发起一轮交互 User turn
-> 将用户消息加入 messages[]

消息数组 messages[]
-> 跨轮次保留，是系统唯一的状态

调用模型 model call
-> 每次调用都会返回停止原因 stop_reason，随后根据它决定下一步
stop_reason: end_turn 本轮结束，回复用户
stop_reason: tool_use 需要使用工具，进入执行工具步骤

执行工具 Run tools
-> 每个工具调用 tool_use 对应一个工具结果 tool_result

追加结果 Append results
-> 把工具结果追加回同一个消息缓冲区
