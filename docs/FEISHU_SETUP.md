# 飞书机器人与 SSH

## 自己的应用与账号

在[飞书开放平台](https://open.feishu.cn/app)创建自己的企业自建应用并启用机器人。如果个人账号还没有组织，按平台引导创建自己的团队。应用可用范围先限制为自己。

应用权限：`im:message.p2p_msg:readonly`、`im:message:send_as_bot`、`im:resource`。可导入 `scripts/feishu-scopes.json`。

- 事件订阅：长连接，`im.message.receive_v1`。
- 回调订阅：长连接，`card.action.trigger`。
- 发布配置后启动控制器，确认长连接成功，再发送 `/绑定 ...`。

`FEISHU_OWNER_OPEN_ID` 可留空，使用首次绑定。只有绑定账号的机器人单聊与登录后的网页接口可以派任务。联系人二维码不是应用身份凭据。

## 控制器到服务器

在控制器机器上配置自己的 SSH 密钥与 SSH config，例如：

```sshconfig
Host workbench-gpu
    HostName gpu.example.org
    User worker
    IdentityFile ~/.ssh/workbench_ed25519
    IdentitiesOnly yes
```

确认 `ssh -o BatchMode=yes workbench-gpu true` 成功。网关、ProxyJump 和自定义端口按自己的集群要求配置。

`native_socket` 必须指向**该机器上已在运行、属于自己的原生 Codex daemon**的 Unix socket。可从原生客户端启动配置或进程参数确认；只读检查可用 `find /tmp -maxdepth 2 -type s -path '*/codex-daemon-*/*'`。如有多个 socket，不要猜测目标，先与该机器的原生服务配置核对。没有 socket 时先按原生客户端的正常方式建立服务，工作台不会代为启动另一版本。

`roots`、`default_cwd` 要替换成实际个人目录；`roots` 限制文件浏览和传图，不替代 Codex 原有执行沙箱。共享同一套会话历史的 CPU/GPU 主机应使用相同 `session_group`，防止工作台并发写入同一会话。

每台服务器沿用其已有 Codex 认证与模型配置。`doctor` 的连接成功不等于模型执行成功；绑定后再在专门测试会话发送一条短任务验证。
