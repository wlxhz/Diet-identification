# Recognition Service

食物识别与克重估算核心。当前以 Python 模块和 Demo 会话服务形式存在。

## 能力

- 食物实例分割和 OpenCV Fallback。
- 烹饪方式推断。
- ArUco 标定。
- 容器、体积和克重估算。
- 营养换算。
- 多帧 Track 聚合。
- 餐具识别和进食事件。

## 目录

```text
backend/models/       Pydantic 数据模型
backend/services/     算法和会话服务
models/               本地模型权重
scripts/              模型下载和调试脚本
tests/                单元测试
static/               Demo 页面
```

## 测试

```powershell
Set-Location services\recognition
..\..\apps\user-web\.venv\Scripts\python.exe -m pytest tests -q
```

## 边界

本模块产生 `FoodTrack` 和 `IntakeEvent`，但不应自行决定用户权限或直接写入监管业务记录。业务持久化由用户业务服务负责。
