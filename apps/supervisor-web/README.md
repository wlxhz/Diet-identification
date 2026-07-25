# Supervisor Web

监管管理端 Flask 应用，负责管理员登录、用户和绑定关系查询、饮食记录、食物库和审计。

## 启动

```powershell
.\scripts\dev\start-supervisor-web.ps1
```

访问 `http://127.0.0.1:5100`。

## 数据

- 用户数据：`.workspace/data/user-web/health.db`
- 管理员和审计：`.workspace/data/supervisor-web/admin.db`

生产环境不应让监管端直接共享 SQLite 文件，应通过统一业务 API 和权限层访问数据。
