# 系统架构总览

## 系统目标

NutritionGlass 通过 Rokid RV101 获取第一视角饮食画面，识别食物名称、烹饪方式和估算克重，生成饮食记录，并向获得授权的监管者展示。

## 逻辑组件

```text
Rokid RV101
  -> apps/rokid-streamer
  -> tools/camera-link
  -> services/recognition
  -> apps/user-web
  -> .workspace/data/user-web/health.db
  -> apps/supervisor-web
```

### `apps/user-web`

负责用户身份、健康目标、共享关系、识别入口和饮食记录。Android 工程位于该目录的 `android/`，构建时将 Flask/Python 和 Web 资源同步到 APK。

### `apps/supervisor-web`

负责管理员和监管端页面、用户查询、绑定关系、饮食记录和审计。当前本地模式直接读取用户 SQLite；后续生产架构应通过中央 API 访问业务数据。

### `apps/rokid-streamer`

运行在 Rokid 眼镜端，负责摄像头采集、H.264/MPEG-TS 编码和 UDP 发送。

### `tools/camera-link`

运行在电脑端，接收眼镜视频，维护最新帧缓冲，提供预览、状态和识别调用。它是设备联调工具和本地识别网关，不应承担用户鉴权或正式业务持久化。

### `services/recognition`

提供食物分割、烹饪方式推断、标定、体积/克重估算、餐具识别、多帧跟踪和进食事件。算法对象和业务记录必须通过明确接口映射，不能直接把每帧结果写为正式摄入。

## 数据边界

- 用户、关系和饮食数据：用户业务域所有。
- 管理员账号和审计：监管管理域所有。
- `FoodTrack`、质量指标和进食事件：识别域产生。
- APK、日志、截图：交付/调试产物，不属于业务数据。
- 完整视频默认不持久化；必要关键帧需明确授权和保留周期。

## 当前部署模式

当前为本机多进程开发模式：

| 服务 | 端口 | 启动脚本 |
|---|---:|---|
| 用户端 | 5000 | `scripts/dev/start-user-web.ps1` |
| Rokid 视频/识别网关 | 9088 | `scripts/dev/start-rokid-backend.ps1` |
| 监管端 | 5100 | `scripts/dev/start-supervisor-web.ps1` |

## 生产演进方向

1. 将用户端和监管端的数据访问迁移到统一 API。
2. 使用 PostgreSQL 等生产数据库替代共享 SQLite。
3. 将识别服务部署为独立进程或 GPU 服务。
4. 使用可靠事件/Outbox 推送监管端。
5. 统一认证、权限、审计、速率限制和可观测性。
