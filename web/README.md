# 飞书内的 Codex 网页工作台

React 手机页面 + NestJS API + 妙搭 PostgreSQL。支持项目/会话切换、历史、模型选择、实时输出更新、排队与明确的「立即引导」按钮。

部署步骤见 [网页部署](../docs/WEB_DEPLOYMENT.md)。必须创建自己的妙搭应用、数据库、OpenAPI Key 和 `WORKBENCH_AUTH`；仓库没有预设账号、服务器或应用注册信息。

开发检查：`npm ci`、`npm run lint`、`npm run build`，Node 22+。生产构建不等于平台运行验证。`npm run dev:local` 需要先在自己的应用工程拉取平台开发环境。

会话 Cookie 为 HttpOnly、Secure；私有接口验证所有者，平台 CSRF 保留。`/openapi/agent` 依赖平台网关 Key 校验。浏览器不保存密码或完整历史正文。
