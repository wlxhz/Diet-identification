# 健康饮食 App — 项目上下文

## 项目概述

一款健康饮食管理应用。核心功能：通过智能眼镜识别摄入的食物 → 计算克重和热量 → 完成饮食记录。

**当前阶段：原型验证**，已实现用户注册、饮食记录看板，并接入工作区内的食物视觉识别算法。

## 技术栈

| 项目 | 选择 | 原因 |
|------|------|------|
| 后端 | Python Flask | 原型阶段服务端渲染最快 |
| 前端 | Jinja2 模板 + Vanilla JS | 零构建，浏览器直接运行 |
| 数据库 | SQLite | 单文件零配置 |
| 认证 | Session + Werkzeug password hash | 服务端会话 |
| 短信验证 | 模拟（数据库存储码 + 页面横幅展示） | 原型阶段不接真实网关 |

## 数据模型

### users 表
- `id` INTEGER PRIMARY KEY
- `phone` TEXT UNIQUE — 中国大陆手机号（`1[3-9]` 开头的 11 位数字）
- `password_hash` TEXT — werkzeug 哈希
- `role` TEXT — 'supervisor' 或 'supervisee'
- `nickname` TEXT — 用户昵称
- `avatar_url` TEXT — 应用内头像文件路径（兼容旧版外部链接）
- `bind_code` TEXT UNIQUE — 监督人的绑定码（8位大写十六进制）
- `bound_to` INTEGER — 被监督人绑定的监督人 ID（外键→users.id）
- `created_at` TIMESTAMP

### verify_codes 表
- `id` INTEGER PRIMARY KEY
- `phone` TEXT — 目标手机号
- `code` TEXT — 6位验证码，5 分钟有效；同一账户 60 秒内不可重复发送
- `used` INTEGER — 是否已使用
- `created_at` TIMESTAMP

### food_library 表
- `id` INTEGER PRIMARY KEY
- `name` TEXT UNIQUE — 食物名称
- `calories_per_100g` REAL — 每100g热量（kcal）
- `category` TEXT — 类别（主食/肉类/水产/蛋奶/蔬菜/水果/饮品/零食）

### diet_records 表
- `id` INTEGER PRIMARY KEY
- `user_id` INTEGER — 外键→users.id
- `food_name` TEXT — 食物名称
- `weight_grams` REAL — 克重
- `calories` REAL — 计算所得热量（kcal）
- `intake_time` TIMESTAMP — 摄入时间
- `created_at` TIMESTAMP

## 角色与权限

### 监督人（supervisor）
- 注册后自动生成 8 位绑定码
- 可查看：自己的饮食 + 所有已绑定被监督人的饮食
- 用户看板：能看到所有用户及绑定关系
- 绑定码长期有效，可被多个被监督人使用

### 被监督人（supervisee）
- 注册时可选填绑定码关联监督人
- 注册后可通过个人主页补绑定
- 饮食看板：仅能看到自己的记录
- 用户看板：仅看到自己 + 自己的监督人

### 数据隔离规则
- 每个用户有独立账号（session 隔离）
- 饮食记录按 user_id 过滤
- 监督人只能看到"已绑定"的被监督人数据
- 独立被监督人（未绑定）的数据对任何监督人都不可见

## 页面清单

| 路由 | 页面 | 说明 |
|------|------|------|
| `/login` | 登录页 | 手机号 + 密码 |
| `/register` | 注册页 | Step1 验证码 → Step2 资料设置 |
| `/dashboard` | 仪表盘 | 登录后的首页，快捷入口 |
| `/diet` | 饮食记录 | 选择食物 + 克重 + 时间 → 自动算热量 |
| `/diet-board` | 饮食看板 | 历史记录表格（按权限过滤） |
| `/user-board` | 用户看板 | 用户列表 + 绑定关系 + 统计 |
| `/profile` | 个人主页 | 个人信息、绑定码、绑定关系管理 |
| `/bind` | 补绑定 | 被监督人专用，输入绑定码关联监督人 |
| `/logout` | 退出 | 清除 session |

## 启动方式

```bash
cd F:\adventureX\apps\user-web
pip install flask
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

启用工作区内的视觉识别能力：

```powershell
python -m pip install -r requirements-recognition.txt
python app.py
```

默认算法目录为相邻的
`..\..\services\recognition`，也可通过
`RECOGNITION_ALGORITHM_DIR` 环境变量覆盖。

## 对话历史（关键决策记录）

1. **看板形态**：本地 Web 应用（Flask + Jinja2）
2. **数据存储**：SQLite
3. **工程化程度**：原型验证
4. **注册方式**：手机号 + 模拟短信验证码（原型阶段不接真实网关）
5. **热量计算**：自动计算（预设 50 种食物库，用户输入克重后系统自动算）
6. **眼镜功能**：Android 原生层通过 Rokid AI App 与 CXR-L 连接 RV101；食物照片只由眼镜 `takePhoto` 获取，并上传到电脑识别服务。浏览器选择图片仅保留为桌面调试入口；识别结果需由用户确认后才写入饮食记录
7. **绑定码规则**：长期有效、一对多、可补绑定
8. **权限**：监督人可查看被监督人数据；数据按 user_id 严格隔离

## 待定 / 下阶段

- 真实短信网关接入（阿里云/腾讯云）
- CXR-M 商务 SDK 的连续低延迟音视频评估（当前 CXR-L 为 700~5000ms 低频 JPEG）
- 头像裁剪与压缩（当前已支持 JPG、PNG、WebP、GIF 本地上传）
- 每日/每周热量统计图表
- 饮食建议与健康报告
- 正式部署与生产环境
