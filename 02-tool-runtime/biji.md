工具运行时Tool Runtime

工具是一份接口契约；调用分发通过查表完成；可以安全并发的调用可以批量执行。

1. 工具注册表 Registry
   名称 -> 工具
   每项能力对应一个注册条目
   通过 schemas() 提供工具的接口定义
2. 调用模型 model call
   模型读取工具的接口定义
   选择工具名称和输入参数
   生产工具调用tool_use，其中包含"名称 + 输入参数"
3. 按名称查找 Lookup by name
   从注册表中查找对应工具并分发调用
   dispatch = registry.get(name)
4. 是否可以安全并发？Concurrency safe?
   读取操作可以批量执行
   写入操作必须避免竞态冲突
   是 -> 并行批量执行 Parallel batch: 依据 is_concurrency_safe 标记
   否 -> 按书按需执行 Run in order: 不可安全并发的调用会打断并行批次
5. 返回工具结果 tool_result
   每个 tool_use 对应一个 tool_result
   将结果追加到消息记录，再次调用模型，继续循环

每个工具都是一个小型对象，包含名称、handler、schema和几个属性。registry依名称保存工具，dispatch则负责查找并执行。

一个工具是一个dataclass
registry 是 name -> tool
添加一项能力，就是注册一个handler
schemas() 返回模型公告的工具列表
run_concurrently 会把标记为 is_concurrency_safe 的工具批量执行
不安全的调用维持顺序执行，所以写入不会相互竞争

tool的 description写的好的5件事

1. 什么时候该用
2. 什么时候不该用
3. 每个参数的真实值是什么样
4. 返回长什么样
5. 调用一次花多少代价
