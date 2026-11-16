# 独立手机网页部署

`web/` 是飞书妙搭的 NestJS/React 应用源码，依赖该平台的网关、CSRF、数据库上下文和托管运行时。它不包含维护者的应用绑定信息，普通 PostgreSQL 或静态托管不能直接替代这些服务。

## 1. 创建自己的妙搭应用

在自己的飞书组织内创建妙搭全代码应用，并按平台提示克隆其生成的 Git 仓库。保留该新应用自己的 `.spark/meta.json`、平台工程配置和 Git remote，将本仓库 `web/` 的业务源码、依赖、脚本和构建配置合入新工程。不要用维护者的应用 ID 或域名。

本仓库删除了原应用的 `.spark` 和内部开发工具指引，不包含任何应用注册凭据。需要通过平台完成新应用初始化。

## 2. 创建数据库表

在**自己的新应用**数据库执行 `web/docs/schema.sql`。它创建命令队列、快照缓存和登录限流三张表，并禁止 anonymous/authenticated 直接读写；服务端仅在验证工作台账号后使用系统数据库上下文。

然后在自己的工程运行 `npm run gen:db-schema`，生成该应用的表类型。不要把既有生产数据库清空来执行这个脚本。原生 Codex 数据库与这些网页表完全无关。

## 3. 设置自己的登录凭据

从仓库根目录运行：

```bash
python3 scripts/create-web-auth.py
```

脚本交互读取账号与密码，在 `.local/web-auth.json` 写入随机盐、PBKDF2 哈希和随机会话签名密钥，权限为 0600，不输出密码。将该文件的 JSON 内容作为新应用的**运行时秘密环境变量** `WORKBENCH_AUTH`。不要放入前端环境、提交仓库或发给别人。

网页没有预设账号与密码。配置缺失时认证会失败。每个使用者生成自己的配置；修改签名密钥会让旧登录失效。

设置 `LOG_REQUEST_BODY=false`、`LOG_RESPONSE_BODY=false`，日志目录放在 `/tmp`。参考 `web/.env.example`。

## 4. 设置控制器接口

发布前，在新应用配置专门的 OpenAPI API Key，仅用于 `POST /openapi/agent`。该路由依赖妙搭网关验证 API Key，不可脱离网关公开暴露。

在控制器自己的 `.env` 填写：

```dotenv
WORKBENCH_SITE_URL=https://YOUR_APP_DOMAIN/app/YOUR_APP_ID
WORKBENCH_AGENT_URL=https://YOUR_APP_DOMAIN/app/YOUR_APP_ID/openapi/agent
WORKBENCH_OPENAPI_KEY=YOUR_PRIVATE_SCOPED_API_KEY
WORKBENCH_CONTROLLER_LABEL=My controller
```

用平台实际返回的网页和 OpenAPI URL 替换示例。Key 只保存于控制器，不放进浏览器源码。控制器主动建立出站 HTTPS，无需对外开放 SSH 或控制器监听端口。

## 5. 发布与接入飞书

在自己的工程完成 `npm run lint`、`npm run build` 后，按平台发布流程提交和发布自己的分支。入口可以允许匿名访问登录页，私有 API 仍验证工作台账号；应用与数据权限必须按上文配置。

发布后重启**自己的工作台控制器**加载新环境。机器人 `/工作台` 可提供网页入口；也可把自己的网页链接加入机器人菜单或飞书工作台，方便手机打开。

## 6. 验收清单

1. 未登录访问 `/api/state`、`/api/history`、`/api/live` 返回 401。
2. 登录后返回自己控制器的机器列表；退出后恢复 401。
3. 检查项目名称、会话名与原生客户端对应。
4. 新建一个测试会话，提交短任务，看到真实输出和历史。
5. 在短任务运行中追加两条消息，确认默认排队；测试「立即引导」与派发前取消。
6. 确认每个使用者都部署独立实例，而非共用同一账号或控制器。

网页使用真实输出的短间隔增量 HTTP 同步；妙搭托管运行时不支持本应用使用 SSE/WebSocket。实际延迟取决于平台和网络。
