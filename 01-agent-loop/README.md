# Agent loop demo

本示例使用 Anthropic Messages 协议，调用模型并执行 `get_time` 工具。

在本目录的 `.env` 中配置：

```dotenv
API_KEY=你的网关密钥
BASE_URL=https://your-gateway.example.com
MODEL=你的网关支持的模型名称
```

网关需要支持 Anthropic Messages 协议。`BASE_URL` 填写网关基础地址，
不要包含末尾的 `/v1` 或 `/v1/messages`，SDK 会自动追加 `/v1/messages`。
程序会将 `API_KEY` 显式传给 Anthropic 客户端，无需改名为 `ANTHROPIC_API_KEY`。

在本目录运行：

```bash
.venv/bin/python demo.py
```

也可以从其他目录使用 Python 和脚本的完整路径运行；程序始终读取脚本旁的 `.env`。
