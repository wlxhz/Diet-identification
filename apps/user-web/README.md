# User Web

用户端健康饮食应用，包含 Flask Web 服务、SQLite 数据访问、识别适配器、页面资源和 Android 容器工程。

## 启动

从仓库根目录运行：

```powershell
.\scripts\dev\start-user-web.ps1
```

## 关键环境变量

- `HEALTH_SECRET_KEY`
- `HEALTH_DB_PATH`
- `HEALTH_RUNTIME_DIR`
- `HEALTH_UPLOAD_DIR`
- `RECOGNITION_ALGORITHM_DIR`

默认本机数据库位于 `.workspace/data/user-web/health.db`。

## 测试

```powershell
.\.venv\Scripts\python.exe tests\browser_smoke.py
```

## Android

Android 工程位于 `android/`。构建时从当前目录同步 Python 和 Web 资源，并可嵌入 `apps/rokid-streamer` 的 Debug APK。
