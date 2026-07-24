# 健康饮食 App — 项目上下文

## 项目概述

一款健康饮食管理应用。核心功能：通过智能眼镜识别摄入的食物 → 计算克重和热量 → 完成饮食记录。

**当前阶段：原型验证**，实现统一用户、双向健康数据共享、独立食物识别和饮食记录。

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
- `role` TEXT — 仅为旧数据库兼容字段，业务逻辑不再区分身份
- `nickname` TEXT — 用户昵称
- `avatar_url` TEXT — 应用内头像文件路径（兼容旧版外部链接）
- `share_code` TEXT UNIQUE — 用户分享码（8位大写字母和数字）
- `bound_to` INTEGER — 旧版单向绑定兼容字段，不再写入
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

## 用户关系与权限

- 所有账号均为统一的个人用户，可记录自己的饮食，也可绑定多位共享伙伴。
- 绑定请求需要对方确认，任意一方都可以拒绝、撤回或解除绑定。
- 双方分别设置自己对对方的备注，备注仅本人可见。
- 双方分别授权饮食记录、健康目标和身体资料，权限可随时关闭。
- 用户只能修改或删除自己的饮食记录；查看伙伴数据时后端必须校验当前授权。
- 旧版 `bound_to` 单向关系会自动迁移为已确认的双向共享关系。

## 页面清单

| 路由 | 页面 | 说明 |
|------|------|------|
| `/login` | 登录页 | 手机号 + 密码 |
| `/register` | 注册页 | Step1 验证码 → Step2 资料设置 |
| `/goal` | 目标看板 | 当前用户的健康目标与营养进度 |
| `/recognition` | 食物识别 | Rokid 或图片识别，确认后写入自己的饮食 |
| `/diet` | 饮食记录 | 手动记录自己的饮食，切换查看已授权伙伴 |
| `/shared/<id>` | 共享资料 | 按授权展示伙伴的目标和身体资料 |
| `/profile` | 个人主页 | 分享码、请求确认、备注和权限管理 |
| `/bind` | 添加伙伴 | 扫码或输入分享码并发送绑定请求 |
| `/logout` | 退出 | 清除 session |

## 启动方式

```bash
cd ~/Desktop/健康饮食
pip install flask
python app.py
# 浏览器打开 http://127.0.0.1:5000
```

## 对话历史（关键决策记录）

1. **看板形态**：本地 Web 应用（Flask + Jinja2）
2. **数据存储**：SQLite
3. **工程化程度**：原型验证
4. **注册方式**：手机号 + 模拟短信验证码（原型阶段不接真实网关）
5. **热量计算**：自动计算（预设 50 种食物库，用户输入克重后系统自动算）
6. **眼镜功能**：Rokid APK 保留 CXR-L/RV101 桥接与识别适配器
7. **分享码规则**：每位用户一个长期有效的 8 位分享码，可绑定多位伙伴
8. **权限**：双向独立授权，饮食、目标、身体资料分项控制

## 待定 / 下阶段

- 真实短信网关接入（阿里云/腾讯云）
- 扩充识别食物库与识别模型覆盖率
- 头像裁剪与压缩（当前已支持 JPG、PNG、WebP、GIF 本地上传）
- 每日/每周热量统计图表
- 饮食建议与健康报告
- 正式部署与生产环境
