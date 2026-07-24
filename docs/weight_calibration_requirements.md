# 克重识别标定卡与精细化估重算法开发需求文档

## 1. 文档目的

本文档用于明确食物视觉识别项目中“克重识别不够精确、长时间视频帧叠加优化效果不好”的解决方案。

本次改造的核心方向是引入自定义实体 `ArUco marker` 标定卡作为标准大小参照物，并在此基础上重构克重估算算法、多帧融合策略、容器模型和前后端展示逻辑。

本文档面向产品、算法、前端、后端共同使用，作为后续开发、分工、验收和迭代的依据。

## 2. 背景与现状问题

当前项目中的克重估算主要依赖单帧画面面积比例：

```text
食物 mask 面积 / 图像总面积 -> 假设餐盘尺度 -> 估算体积 -> 乘以食物密度 -> 克重
```

现有算法的问题是：

1. 画面面积比例不是物理面积。手机靠近或远离食物时，同一份食物在图像中的占比变化很大，导致克重漂移。
2. 当前使用固定经验值推导体积，缺少真实世界尺度参照。
3. 多帧融合目前主要是对历史估重做平滑，不能纠正初始估重偏差。
4. 长时间视频帧叠加会让错误结果更稳定，但不一定更准确。
5. 当前未区分“有标定卡参与的精确估重”和“无标定卡的粗估”。
6. 碗、盒、盘等容器会显著影响可见面积和真实体积，现有算法缺少容器模型。

因此，本次需求不再把“更多帧”作为克重精度的主要解法，而是把“真实尺度 + 食物形态模型 + 容器模型 + 有效帧筛选”作为主要路径。

## 3. 产品目标

### 3.1 核心目标

通过自定义 `ArUco marker` 实体标定卡，为图像提供真实世界尺度，使系统能够更稳定地完成营养估算级克重识别。

系统不是电子秤替代品，目标是服务于饮食记录、营养估算、食物摄入事件判断和用餐过程记录。

### 3.2 用户体验目标

1. 用户吃饭时只需要将标定卡自然放在餐盘、餐盒或食物旁边。
2. 不强制用户每次必须放置标定卡。
3. 如果检测到标定卡，系统输出“标定卡参与估重”的结果。
4. 如果未检测到标定卡，系统仍可识别食物并输出粗估结果，但需要明显降低置信度并提示“未使用标定卡”。
5. 不要求用户手动输入食物高度、容器尺寸、份量大小等信息。
6. 系统应在后台通过低频采集判断食物剩余量变化，并重点识别用户用筷子、勺子、叉子等餐具夹起或舀起食物后的进食事件，记录用户实际摄入的食物数据。

### 3.3 精度目标

第一版目标定位为“营养估算级克重识别”，不承诺电子秤精度。

建议验收目标：

| 食物/场景 | 有标定卡目标误差 | 无标定卡目标误差 | 说明 |
|---|---:|---:|---|
| 单一实体食物，如蛋糕、面包、鸡排、馒头、水果块 | ±15%-25% | ±35%-60% | 形状稳定，适合视觉估重 |
| 米饭、炒饭、面条、薯类 | ±20%-35% | ±45%-70% | 需要高度先验 |
| 普通炒菜、青菜、混合菜 | ±30%-45% | 仅粗估 | 堆叠、遮挡、空隙影响大 |
| 碗装饭、餐盒饭 | ±25%-45% | 仅粗估 | 依赖容器模型 |
| 汤、粥、液体、透明容器 | 第一版低置信度粗估 | 不建议估重 | 需要更强容器/液面模型 |

## 4. 标定卡需求

### 4.1 标定卡形态

第一版使用自定义实体 `ArUco marker` 标定卡。

标定卡定位：

1. 当前阶段先作为可打印实体卡使用。
2. 后续可扩展为标准化品牌硬件。
3. 标定卡的主要功能是提供标准尺寸参照。
4. 标定卡也作为距离和尺度变化参照，用于辅助判断食物区域大小变化、餐具夹取/舀取路径、剩余量变化和摄入完成状态。

### 4.2 标定卡规格

第一版固定规格：

| 项目 | 规格 |
|---|---|
| marker 类型 | ArUco marker |
| 字典 | `DICT_5X5_100` |
| marker ID | 优先 `23`，备用 `42` |
| marker 物理尺寸 | `50mm x 50mm` |
| 标定卡形式 | 打印实体卡 |
| 放置方式 | 画面任意角落，完整可见即可 |
| 是否强制使用 | 不强制 |

注意：算法中的 `marker_size_mm` 必须配置为 `50.0`，不能依赖图像像素推断。

### 4.3 标定卡制作方式

第一版需要提供一份可打印文件，建议包含：

1. 一个 `50mm x 50mm` 的 `ArUco DICT_5X5_100 ID=23` marker。
2. marker 外侧保留白边，避免裁切影响识别。
3. 标注“打印时请使用 100% 比例，不要缩放”。
4. 可增加品牌名称和使用提示，但不能进入 marker 内部区域。
5. 可提供 PDF 和 PNG 两种文件：
   - PDF 用于打印。
   - PNG 用于开发调试和文档展示。

建议设计：

```text
整卡尺寸：70mm x 70mm 或银行卡大小
有效 marker：50mm x 50mm
marker 外白边：至少 5mm
品牌/说明文字：放在 marker 外侧
```

打印要求：

1. 使用白色硬卡纸或覆膜卡片。
2. 黑白对比清晰。
3. 不反光或低反光。
4. 打印比例必须为 100%。
5. 打印后应使用尺子校验 marker 外边长是否为 50mm。

### 4.4 标定卡摆放要求

用户侧规则：

1. 标定卡放在餐盘、餐盒、碗或食物旁边即可。
2. 标定卡需要完整可见，不能被食物、餐具、手部遮挡。
3. 标定卡可以位于画面任意角落。
4. 标定卡不需要紧贴食物，但建议和食物处于相近距离。
5. 标定卡应尽量平放在桌面或托盘上。
6. 标定卡倾斜过大、反光、模糊或太小时，系统应提示标定质量不足。

算法侧规则：

1. 只有完整检测到 marker 四角时，才认为标定卡可参与估重。
2. marker 过小、过斜、边缘模糊、透视畸变过强时，应降低 `scale confidence`。
3. 有标定卡但质量不足时，食物仍可识别，但该帧不进入有效估重融合。

## 5. 标定卡识别方案

### 5.1 技术依赖

正式后端依赖改为：

```text
opencv-contrib-python-headless
```

原因：

1. `cv2.aruco` 位于 OpenCV contrib 模块。
2. 相比自定义图案识别，`ArUco marker` 检测稳定、实现快、可维护性好。
3. 适合第一版快速验证克重改造链路。

### 5.2 检测流程

每帧图像进入分析后，先执行标定卡检测：

```text
输入帧
-> 灰度化
-> ArUco detector 检测 marker
-> 过滤 marker ID
-> 提取 marker 四角像素坐标
-> 根据 50mm 实际边长计算 mm_per_px
-> 计算 marker 透视质量、面积质量、清晰度质量
-> 输出 scale metadata
```

第一版只接受：

```text
marker ID in {23, 42}
```

如果同时检测到 ID 23 和 42：

1. 优先使用面积更大、角点更清晰、透视变形更小的 marker。
2. 多 marker 融合留作二期。

### 5.3 尺度计算

根据 marker 四条边的像素长度计算平均边长：

```text
edge_px = mean(length(top), length(right), length(bottom), length(left))
mm_per_px = 50.0 / edge_px
```

如果存在明显透视变形，需要分别记录长边、短边和透视质量：

```text
edge_ratio = min(edge_lengths) / max(edge_lengths)
```

建议：

```text
edge_ratio >= 0.72：可接受
edge_ratio < 0.72：标定质量偏低
edge_ratio < 0.55：不参与有效估重
```

### 5.4 标定质量评分

输出 `scale confidence`，范围 `0.0-1.0`。

建议评分因子：

| 因子 | 含义 |
|---|---|
| marker 面积占比 | 太小则角点误差大 |
| 边长一致性 | 透视越严重，质量越低 |
| 角点清晰度 | 模糊、压缩、反光会降低质量 |
| 是否完整入镜 | 四角必须完整 |
| marker ID 是否匹配 | 只接受指定 ID |

示例评分：

```text
scale_confidence =
  area_score * 0.30
+ perspective_score * 0.30
+ sharpness_score * 0.25
+ id_score * 0.15
```

有效估重帧建议阈值：

```text
scale_confidence >= 0.55
```

低于阈值时：

1. 食物识别照常进行。
2. 当前帧不参与克重融合。
3. 前端提示“标定卡质量不足”。

## 6. 克重计算算法改造

### 6.1 总体思路

从原来的画面比例估重：

```text
area_ratio -> 经验体积 -> 密度 -> 克重
```

升级为真实尺度估重：

```text
mask_area_px
-> mm_per_px
-> area_cm2
-> 食物高度/厚度模型
-> volume_ml
-> density_g_per_ml
-> weight_g
```

### 6.2 有标定卡估重公式

当一帧中存在有效标定卡：

```text
area_mm2 = mask_area_px * mm_per_px * mm_per_px
area_cm2 = area_mm2 / 100
volume_ml = area_cm2 * estimated_height_cm * shape_factor
weight_g = volume_ml * density_g_per_ml
```

说明：

1. `1ml = 1cm3`。
2. `estimated_height_cm` 由食物类别、形态、容器、mask 特征自动估计。
3. `shape_factor` 用于修正食物不是完整规则柱体的问题。
4. `density_g_per_ml` 沿用并扩展现有 `nutrition.py` 中的食物密度表。

### 6.3 无标定卡估重公式

当一帧中没有有效标定卡：

1. 可以保留现有粗估算法作为 fallback。
2. 输出中必须标记：

```text
weight_source = "visual_fallback"
reference_detected = false
scale_confidence = 0
```

3. 无标定卡帧不参与精确克重融合。
4. 无标定卡结果应降低 `weight_confidence`，并在前端提示“未检测到标定卡，当前克重为粗估”。

### 6.4 食物高度模型

用户不需要输入食物高度。系统根据食物类别和视觉形态自动推断。

需要新增 `FoodVolumeProfile` 或扩展现有 `FoodProfile`。

建议字段：

```python
class FoodVolumeProfile:
    profile_key: str
    default_height_cm: float
    min_height_cm: float
    max_height_cm: float
    shape_factor: float
    volume_confidence: float
    volume_model: str
```

建议模型类型：

| volume_model | 适用食物 | 计算方式 |
|---|---|---|
| `flat_solid` | 饼干、薄蛋糕、煎蛋、肉片 | 面积 * 固定厚度 |
| `block_solid` | 蛋糕、面包、馒头、鸡排 | 面积 * 类别厚度 * 形态修正 |
| `mound` | 米饭、炒饭、面条、土豆泥 | 面积 * 堆叠高度模型 |
| `loose_leafy` | 青菜、沙拉 | 面积 * 低密度蓬松修正 |
| `container_fill` | 碗装饭、粥、汤、餐盒饭 | 容器面积 * 填充高度/比例 |
| `unknown` | 未知食物 | 低置信度粗估 |

示例初始参数：

| 食物类型 | 默认高度 | shape_factor | 说明 |
|---|---:|---:|---|
| 饼干/薄片零食 | 0.4-0.8cm | 0.85 | 平面近似较可靠 |
| 蛋糕/面包 | 2.5-4.0cm | 0.80 | 形状较稳定 |
| 鸡排/肉块 | 1.5-2.5cm | 0.75 | 厚度变化中等 |
| 米饭/炒饭 | 2.0-3.5cm | 0.65 | 堆叠模型 |
| 面条 | 1.8-3.0cm | 0.55 | 空隙较多 |
| 青菜 | 2.0-5.0cm | 0.35 | 蓬松、遮挡大 |
| 混合菜 | 1.5-3.5cm | 0.50 | 置信度较低 |
| 汤/粥 | 容器模型 | 低置信度 | 需要容器和液面 |

### 6.5 食物可估重等级

需要区分“适合精确估重”和“不适合精确估重”的食物。

建议输出：

```text
weight_estimation_level:
  calibrated
  approximate
  rough
  unsupported
```

定义：

| level | 含义 |
|---|---|
| `calibrated` | 有标定卡参与，且食物类型适合估重 |
| `approximate` | 有标定卡，但食物/容器复杂，误差较高 |
| `rough` | 无标定卡，仅视觉粗估 |
| `unsupported` | 汤、透明容器、严重遮挡等不建议估重 |

前端不能只显示克重数字，还需要显示估重等级或标定状态。

## 7. 容器模型需求

### 7.1 容器模型目标

第一版需要纳入容器模型，但定位为粗粒度可用模型，不追求复杂 3D 重建。

目标：

1. 支持常见碗、盘、餐盒的粗略识别。
2. 对容器内食物估重提供更合理的面积边界和体积约束。
3. 对汤、粥、液体类食物明确降低置信度。
4. 为后续标准容器库和品牌硬件扩展留接口。

### 7.2 第一版容器类型

| 容器类型 | 识别方式 | 用途 |
|---|---|---|
| 平盘 | 圆/椭圆边缘检测，食物位于盘内 | 限定食物平面和尺度 |
| 碗 | 椭圆口检测，中心区域食物/液体 | 粗估碗口面积和填充区域 |
| 矩形餐盒 | 直线/矩形轮廓检测 | 餐盒饭、外卖盒估重 |
| 无容器 | 食物直接在桌面/纸袋/包装上 | 使用食物 mask 面积 |

### 7.3 容器估重原则

有标定卡时：

```text
容器像素尺寸 -> 真实尺寸
食物 mask 与容器区域关系 -> 填充比例
类别高度/容器默认深度 -> 体积
```

无标定卡时：

1. 容器只用于辅助识别，不参与精确估重。
2. 输出粗估结果。

### 7.4 容器模型第一版限制

第一版不解决以下高难场景：

1. 透明玻璃容器。
2. 深碗中液面不可见。
3. 食物被大量餐具遮挡。
4. 多层堆叠不可见高度。
5. 容器和标定卡处于明显不同深度平面。

这些场景需要输出低置信度或不支持精确估重。

## 8. 低频采集、餐具进食事件与摄入判断

### 8.1 采集频率

目标场景是用户正常吃饭过程中的自然采集。系统不仅需要识别碗、盘、餐盒中的食物剩余量，更关键的是识别用户通过筷子、勺子、叉子等餐具夹起或舀起食物并送入口中的过程。

建议频率：

```text
每分钟 10-15 帧
即每 4-6 秒采集 1 帧
```

与当前高频连续推流不同，后续应改为低频关键帧采集，降低计算压力和用户设备负担。

需要注意：每分钟 10-15 帧适合长期用餐记录和剩余量趋势判断，但对“夹起 -> 入口”的快速动作可能存在漏检。因此第一版需要同时支持两种采集模式：

| 模式 | 频率 | 用途 |
|---|---:|---|
| 常规低频模式 | 每分钟 10-15 帧 | 长时间用餐记录、剩余量变化、粗粒度摄入事件 |
| 事件增强模式 | 检测到餐具/手部活动时短时提高采样 | 捕捉夹起、舀起、送入口中的关键帧 |

事件增强模式可以在检测到以下信号时触发：

1. 餐具进入食物容器区域。
2. 餐具附近出现食物小块或食物 mask。
3. 餐具从容器区域向画面上方、侧上方或用户口部方向移动。
4. 标定卡尺度显示相机距离稳定，但食物小块位置发生明显移动。

### 8.2 摄入事件判断目标

系统需要通过食物距离、标定尺度、餐具检测、食物 mask 面积变化、食物随餐具移动轨迹和 track 状态变化，判断用户实际摄入了哪些食物，并记录对应食物数据。

这里的“摄入”不是通过单帧消失立即判断，也不能只依赖盘中剩余量减少。第一版需要建立两条证据链：

1. **容器侧证据**：碗、盘、餐盒中的某类食物剩余量下降。
2. **餐具侧证据**：筷子、勺子、叉子等餐具携带食物离开容器，并进入合理的进食路径。

最终摄入记录应优先以餐具侧事件为核心，容器侧剩余量作为校验和补偿。

### 8.3 餐具与进食对象

第一版需要识别或跟踪的对象：

| 对象 | 说明 |
|---|---|
| 筷子 | 细长双杆，夹取小块食物，适合中餐场景 |
| 勺子 | 可舀取米饭、粥、汤、混合菜，食物常位于勺面 |
| 叉子 | 可叉取固体食物，食物常位于叉尖附近 |
| 手部 | 可作为餐具辅助信号，但第一版不以手势识别为主 |
| 口部/脸部区域 | 用于判断餐具是否进入进食区域，涉及隐私和视角限制 |
| 食物小块/勺中食物 | 需要和来源食物 track 做归属匹配 |

第一版建议优先支持：

```text
筷子夹取固体/半固体食物
勺子舀取米饭、混合菜、粥类
叉子叉取实体食物
```

不建议第一版强依赖精确口部识别。口部检测可以作为增强信号，而不是必须条件。原因是正常用餐场景中，镜头不一定包含用户脸部，且口部识别涉及隐私敏感性。

### 8.4 摄入事件状态机

每一次潜在进食动作建立 `IntakeEvent`，状态机如下：

```text
idle
-> utensil_detected
-> utensil_contact_food
-> food_lifted
-> moving_to_mouth
-> intake_confirmed / returned_to_plate / uncertain
```

状态定义：

| 信号 | 说明 |
|---|---|
| `idle` | 未检测到进食相关动作 |
| `utensil_detected` | 检测到筷子、勺子、叉子等餐具 |
| `utensil_contact_food` | 餐具进入某个食物或容器区域 |
| `food_lifted` | 餐具附近出现随餐具移动的食物区域 |
| `moving_to_mouth` | 餐具和食物离开容器，向口部/画面上方/用户方向移动 |
| `intake_confirmed` | 食物从餐具区域消失，且未返回容器，判断为已摄入 |
| `returned_to_plate` | 食物随餐具移动后又回到容器或盘中 |
| `uncertain` | 遮挡、缺帧、标定不足或轨迹不完整，不能确认 |

### 8.5 摄入事件判断依据

建议结合以下信号：

| 信号 | 说明 |
|---|---|
| 标定卡尺度 | 判断相机距离变化，避免把距离变化误判为食物移动或减少 |
| 餐具位置与方向 | 判断餐具是否进入食物区域、是否离开容器 |
| 餐具与食物 mask 的接触关系 | 判断是否发生夹取/舀取 |
| 餐具附近食物小块面积 | 估算本次夹取或舀取的食物重量 |
| 食物小块与来源食物的颜色/纹理/类别相似度 | 将摄入事件归属到具体食物 |
| 食物真实面积 cm2 | 有标定卡时估算餐具上食物小块的面积 |
| 餐具运动轨迹 | 判断是否朝用户口部方向移动 |
| 口部/脸部区域 | 可选增强信号，不作为第一版强依赖 |
| 容器剩余量变化 | 作为摄入事件的校验或补偿 |
| 时间窗口 | 避免瞬时遮挡或餐具经过造成误判 |

### 8.6 单次夹取/舀取克重估算

当检测到餐具携带食物时，需要估算本次摄入事件的克重。

有标定卡时：

```text
utensil_food_area_px
-> mm_per_px
-> utensil_food_area_cm2
-> bite_height_model
-> bite_volume_ml
-> bite_weight_g
```

无标定卡时：

1. 可以记录摄入事件存在。
2. 可以做低置信度粗估。
3. 不应将该事件作为高精度营养摄入数据。

不同餐具的估重方式：

| 餐具 | 估重方式 |
|---|---|
| 筷子 | 根据夹起食物小块 mask 面积、类别厚度、形态系数估算 |
| 勺子 | 优先检测勺面区域和勺内填充比例，结合勺子可见尺寸估算 |
| 叉子 | 根据叉尖附近食物 mask 面积和类别厚度估算 |

如果餐具上的食物小块无法稳定分割，则退化为容器剩余量差分：

```text
本次摄入估计 = 上一稳定容器重量 - 当前稳定容器重量
```

差分结果需要经过时间窗口和异常值过滤，避免把搅拌、遮挡、翻动误判为摄入。

### 8.7 食物来源归属

每个 `IntakeEvent` 必须尽量归属到一个来源食物 track。

归属依据：

1. 餐具接触前最近的容器/食物区域。
2. 餐具附近食物颜色、纹理和当前食物 profile 的相似度。
3. 餐具离开时与哪个食物 mask 相交或距离最近。
4. 当前 meal 中各食物的空间位置。
5. 如果是混合菜或勺中多种食物，则允许一个事件归属多个食物，并按面积比例或置信度拆分。

输出建议：

```text
source_track_id
source_profile_key
source_confidence
mixed_sources
```

### 8.8 食物剩余状态机

每个食物 track 仍然需要维护剩余状态，但它不再是摄入判断的唯一依据。

```text
observing -> active -> decreasing -> nearly_finished -> finished / lost / uncertain
```

| 状态 | 含义 |
|---|---|
| `observing` | 初次识别，样本不足 |
| `active` | 稳定存在，正在记录 |
| `decreasing` | 容器剩余量下降，或存在已确认摄入事件 |
| `nearly_finished` | 剩余估重低于初始估重一定比例 |
| `finished` | 长时间未恢复且剩余量低 |
| `lost` | 目标消失，但可能只是遮挡或移出画面 |
| `uncertain` | 标定不足或遮挡严重，无法判断 |

### 8.9 完成判断规则

建议第一版规则：

```text
initial_weight = 前 N 个有效标定帧的 weighted median
current_weight = 最近 M 个有效标定帧的 weighted median
remaining_ratio = current_weight / initial_weight
intake_weight_sum = 已确认 IntakeEvent 的摄入重量总和
```

进入 `nearly_finished`：

```text
remaining_ratio <= 0.20
或 intake_weight_sum / initial_weight >= 0.80
且最近 2-3 个有效帧或摄入事件均支持该趋势
```

进入 `finished`：

```text
remaining_ratio <= 0.10
或 intake_weight_sum / initial_weight >= 0.90
或目标在容器区域内连续缺失超过指定时间
且不存在明显遮挡、移出画面、夹起后放回等迹象
```

无标定卡时：

1. 可以识别餐具进食事件，但摄入克重为低置信度粗估。
2. 不使用估重下降作为强判断。
3. 仅根据视觉存在、消失、餐具事件做弱判断。
4. 状态最多进入 `uncertain` 或低置信度 `decreasing`，不应高置信度标记 `finished`。

## 9. 多帧融合策略

### 9.1 核心原则

多帧融合不再简单叠加所有视频帧，而是只融合有效估重帧。

有效估重帧条件：

1. 食物被稳定识别。
2. mask 或 bbox 质量达标。
3. 如果有标定卡参与，则标定卡必须完整可见。
4. `scale_confidence >= 0.55`。
5. 食物未明显被遮挡。
6. 当前帧不是运动模糊或曝光异常。

### 9.2 有标定卡帧

如果有标定卡参与：

```text
有效估重帧必须检测到标定卡
无标定卡帧只用于识别和追踪，不参与克重融合
```

这条规则用于避免尺度漂移污染融合结果。

### 9.3 无标定卡帧

无标定卡帧可以用于：

1. 食物识别。
2. 食物 track 追踪。
3. 食物是否仍在画面中。
4. 粗略状态展示。

无标定卡帧不能用于：

1. 精确克重融合。
2. 初始重量基准。
3. 高置信度摄入完成判断。

### 9.4 融合算法

每个食物 track 维护独立观测样本：

```python
class WeightObservation:
    timestamp_ms: int
    frame_index: int
    track_id: str
    weight_g: float
    raw_weight_g: float
    volume_ml: float
    area_cm2: float
    scale_mm_per_px: float
    scale_confidence: float
    mask_confidence: float
    weight_source: str
    container_type: str
    occlusion_score: float
```

融合方式：

```text
weighted median 或 trimmed mean
权重 = scale_confidence * mask_confidence * food_confidence * view_quality
```

建议不再把某个早期重量固定为长期 `reference_weight_g`。

新的 reference 应该是尺度和观测集合：

```text
reference_scale_mm_per_px
accepted_observations
initial_weight_distribution
current_weight_distribution
```

### 9.5 异常值过滤

如果某一帧估重与最近稳定结果差异过大：

```text
abs(current - median_recent) / median_recent > 0.55
```

则标记为 outlier，不参与融合，除非连续多帧都支持新趋势。

## 10. 后端数据模型改造

### 10.1 FoodTrack 新增字段

建议为 `FoodTrack` 增加：

```python
reference_detected: bool = False
reference_type: str = "none"  # none / aruco
reference_marker_id: int | None = None
scale_mm_per_px: float = 0
scale_confidence: float = 0
weight_source: str = "visual_fallback"  # aruco_calibrated / visual_fallback / container_model
weight_estimation_level: str = "rough"  # calibrated / approximate / rough / unsupported
area_cm2: float = 0
estimated_height_cm: float = 0
shape_factor: float = 0
container_type: str = "none"
container_confidence: float = 0
occlusion_score: float = 0
consumption_state: str = "observing"
remaining_ratio: float | None = None
intake_weight_sum_g: float = 0
confirmed_intake_event_count: int = 0
last_intake_event_at: int | None = None
```

### 10.2 IntakeEvent 新增模型

建议新增 `IntakeEvent`，用于记录一次夹取、舀取、叉取和入口事件。

```python
class IntakeEvent:
    event_id: str
    state: str  # utensil_detected / food_lifted / moving_to_mouth / intake_confirmed / returned_to_plate / uncertain
    utensil_type: str  # chopsticks / spoon / fork / hand / unknown
    source_track_id: str | None
    source_profile_key: str = "unknown_food"
    source_confidence: float = 0
    mixed_sources: list[dict] = []
    estimated_bite_weight_g: float = 0
    bite_weight_error_g: float = 0
    bite_area_cm2: float = 0
    bite_volume_ml: float = 0
    weight_source: str = "visual_fallback"
    reference_detected: bool = False
    scale_confidence: float = 0
    trajectory_confidence: float = 0
    intake_confidence: float = 0
    started_at_ms: int
    confirmed_at_ms: int | None = None
```

### 10.3 MeasurementQuality 新增字段

建议增加：

```python
reference_visibility: float = 0
scale_quality: float = 0
container_visibility: float = 0
calibrated_frame_ratio: float = 0
utensil_visibility: float = 0
intake_event_quality: float = 0
```

### 10.4 Report 新增字段

最终报告中需要明确：

```text
total_weight_g
total_weight_error_g
total_intake_weight_g
calibrated_weight_g
rough_weight_g
calibrated_food_count
rough_food_count
reference_used
reference_coverage_ratio
consumption_records
intake_events
utensil_event_count
confirmed_intake_event_count
```

每个食物的报告应包含：

```text
是否使用标定卡
估重等级
初始重量
最终剩余重量
摄入估计重量
摄入状态
摄入事件数量
主要餐具类型
置信度
主要误差来源
```

## 11. 后端模块改造建议

### 11.1 新增模块

建议新增：

```text
backend/services/calibration.py
backend/services/volume_estimator.py
backend/services/container_detector.py
backend/services/utensil_tracker.py
backend/services/consumption_tracker.py
```

职责：

| 模块 | 职责 |
|---|---|
| `calibration.py` | 检测 ArUco marker，输出尺度和质量 |
| `volume_estimator.py` | 根据真实面积、类别、容器估算体积和重量 |
| `container_detector.py` | 检测碗、盘、餐盒等容器 |
| `utensil_tracker.py` | 检测筷子、勺子、叉子，跟踪餐具与食物小块轨迹 |
| `consumption_tracker.py` | 融合餐具摄入事件和容器剩余量，判断实际摄入数据和完成状态 |

### 11.2 analyzer.py 改造

`FoodAnalyzer.analyze()` 流程建议调整为：

```text
decode frame
-> detect calibration marker
-> detect food mask / bbox / class
-> detect container
-> detect utensil and lifted food candidates
-> estimate food area in cm2 if scale available
-> estimate volume and weight
-> estimate bite weight for utensil-carried food if available
-> output FoodTrack with calibration metadata
```

### 11.3 session_store.py 改造

`SessionStore` 不再把稳定帧重量作为唯一 reference。

改造方向：

1. 维护每个 track 的 `WeightObservation` 列表。
2. 有标定卡帧进入 calibrated observation。
3. 无标定卡帧只更新追踪状态。
4. 使用 `weighted median` 输出当前重量。
5. 维护每个餐具动作的 `IntakeEvent` 列表。
6. 增加食物摄入状态机。
7. 支持低频长期采集和餐具活动触发的短时增强采样。

## 12. 前端需求

### 12.1 采集端

采集端需要支持低频采集：

```text
每 4-6 秒上传 1 帧
即每分钟 10-15 帧
```

当前 demo 的高频 `520ms` 上传可以保留为调试模式。正式体验默认低频，但当检测到餐具进入食物区域、餐具携带食物离开容器、或画面中出现疑似进食动作时，需要短时提高采样频率以捕捉摄入事件。

采集端不要求用户手动输入信息。

### 12.2 实时提示

需要显示：

1. 是否检测到标定卡。
2. 标定卡质量是否达标。
3. 当前克重是“标定卡估重”还是“视觉粗估”。
4. 如果标定卡未参与，提示“当前为粗估”。
5. 如果食物类型不适合精确估重，提示低置信度。
6. 餐具进食事件状态，如“检测到夹取”“疑似入口”“已记录一口”“无法确认”。
7. 食物剩余状态，如“正在记录”“可能减少”“接近完成”“已完成/待确认”。

### 12.3 Dashboard 展示

每个食物条目建议展示：

```text
食物名称
估计克重
误差范围
是否使用标定卡
估重等级
剩余比例
摄入状态
已确认摄入重量
摄入事件数量
最近一次餐具类型
置信度
```

总览区建议展示：

```text
总克重
其中标定卡参与克重
粗估克重
标定卡覆盖率
当前采集质量
已确认摄入总量
餐具事件数量
```

## 13. API 与字段建议

### 13.1 单帧上传

现有接口可继续使用：

```text
POST /api/sessions/{session_id}/frames
```

请求字段可保持兼容：

```json
{
  "token": "...",
  "image": "data:image/jpeg;base64,...",
  "width": 640,
  "height": 360,
  "timestamp_ms": 123456789,
  "device_motion": {}
}
```

后续可以扩展 `device_motion`，但第一版不依赖用户手机姿态。

### 13.2 状态响应

`foods[]` 中新增字段示例：

```json
{
  "name": "米饭",
  "estimated_weight_g": 138.5,
  "weight_error_g": 32.4,
  "reference_detected": true,
  "reference_type": "aruco",
  "reference_marker_id": 23,
  "scale_mm_per_px": 0.42,
  "scale_confidence": 0.81,
  "weight_source": "aruco_calibrated",
  "weight_estimation_level": "calibrated",
  "area_cm2": 68.4,
  "estimated_height_cm": 2.6,
  "shape_factor": 0.65,
  "container_type": "bowl",
  "container_confidence": 0.62,
  "consumption_state": "active",
  "remaining_ratio": 0.84,
  "intake_weight_sum_g": 31.2,
  "confirmed_intake_event_count": 2
}
```

状态响应中建议新增 `intake_events[]`：

```json
{
  "event_id": "intake_0007",
  "state": "intake_confirmed",
  "utensil_type": "chopsticks",
  "source_track_id": "food_1",
  "source_profile_key": "chicken",
  "source_confidence": 0.76,
  "estimated_bite_weight_g": 12.4,
  "bite_weight_error_g": 4.8,
  "weight_source": "aruco_calibrated",
  "reference_detected": true,
  "scale_confidence": 0.81,
  "trajectory_confidence": 0.68,
  "intake_confidence": 0.72
}
```

## 14. 验收标准

### 14.1 标定卡检测验收

1. 可识别打印的 `50mm x 50mm` ArUco 标定卡。
2. 可输出 marker ID、四角坐标、`mm_per_px`、`scale_confidence`。
3. 对 ID 23 和 42 均可识别。
4. 对非指定 marker ID 不参与估重。
5. marker 太小、遮挡、严重倾斜时能降低置信度或拒绝参与估重。

### 14.2 克重估算验收

使用同一份食物，在不同拍摄距离下测试：

1. 有标定卡时，估重应显著小于无标定卡时的距离漂移。
2. 同一食物不同距离估重相对波动建议小于 20%-30%。
3. 无标定卡时必须标记为粗估。
4. 不适合精确估重的食物必须降低置信度。

### 14.3 多帧融合验收

1. 有效估重帧必须包含合格标定卡。
2. 无标定卡帧不得污染 calibrated weight。
3. 异常帧不会明显拉偏最终结果。
4. `weighted median` 或 `trimmed mean` 输出稳定结果。

### 14.4 餐具摄入事件验收

1. 能检测筷子、勺子、叉子进入食物区域的动作。
2. 能识别餐具附近随餐具移动的食物小块或勺中食物。
3. 有标定卡时，能对单次夹取/舀取食物输出低误差克重估计。
4. 能将摄入事件归属到来源食物 track。
5. 食物被夹起后又放回盘中时，应标记 `returned_to_plate`，不能计入摄入。
6. 餐具短暂经过食物上方但未带走食物时，不能生成 confirmed intake。
7. 口部不在画面中时，仍可基于餐具轨迹和食物消失生成低到中置信度摄入事件。
8. 无标定卡时可以记录摄入事件，但克重应标记为粗估。

### 14.5 摄入完成判断验收

1. 同一食物逐渐减少时，系统能进入 `decreasing`。
2. 剩余量低于阈值并稳定后，可进入 `nearly_finished`。
3. 食物短暂遮挡时不能立即判断为 `finished`。
4. 有多个 confirmed intake events 且累计摄入接近初始重量时，可进入 `finished` 或 `nearly_finished`。
5. 无标定卡时不能高置信度判断摄入完成。

## 15. 开发里程碑

### Milestone 1：标定卡生成与检测

1. 生成 `DICT_5X5_100 ID=23` 和 `ID=42` 标定卡。
2. 提供 PDF/PNG 打印文件。
3. 新增 `calibration.py`。
4. 接入 `opencv-contrib-python-headless`。
5. 输出 `mm_per_px` 和 `scale_confidence`。

### Milestone 2：真实尺度克重估算

1. 新增 `volume_estimator.py`。
2. 根据 `mm_per_px` 将 mask 面积转换为 `area_cm2`。
3. 建立食物高度和形态先验。
4. 输出 `weight_source` 和 `weight_estimation_level`。
5. 无标定卡保留粗估 fallback。

### Milestone 3：容器模型

1. 新增 `container_detector.py`。
2. 支持平盘、碗、矩形餐盒识别。
3. 将容器类型引入体积估算。
4. 对汤、粥、液体场景输出低置信度。

### Milestone 4：餐具检测与单次摄入事件

1. 新增 `utensil_tracker.py`。
2. 支持筷子、勺子、叉子的检测和简易轨迹跟踪。
3. 检测餐具进入食物区域、夹起/舀起食物、离开容器的事件。
4. 新增 `IntakeEvent` 数据模型。
5. 有标定卡时估算单次夹取/舀取克重。
6. 支持夹起后放回盘中的 `returned_to_plate` 判断。

### Milestone 5：多帧融合重构

1. 新增 `WeightObservation`。
2. 用 `weighted median` 替代早期重量锁定。
3. 有标定卡帧参与克重融合。
4. 无标定卡帧只参与识别和追踪。
5. 增加异常值过滤。
6. 将 confirmed `IntakeEvent` 计入摄入重量累计。

### Milestone 6：低频采集与摄入状态

1. 采集频率调整为每分钟 10-15 帧。
2. 新增 `consumption_tracker.py`。
3. 实现 `observing -> active -> decreasing -> nearly_finished -> finished/lost/uncertain` 状态机。
4. 支持餐具活动触发短时增强采样。
5. 报告中记录初始重量、剩余重量、摄入估计重量和摄入事件列表。

### Milestone 7：前端展示与验收集

1. Dashboard 展示标定卡状态、估重等级、摄入状态和餐具摄入事件。
2. 采集端提示标定卡质量。
3. 建立小型测试集，包含真实称重值。
4. 完成不同距离、不同容器、不同食物类型、不同餐具动作的回归测试。

## 16. 风险与限制

1. 单个 ArUco marker 只能提供局部尺度，不能完整解决食物高度问题。
2. 如果标定卡和食物距离差异太大，尺度会有误差。
3. 手机广角镜头边缘畸变会影响角落 marker 的尺度精度。
4. 食物被遮挡、混合、翻动后，track 连续性可能下降。
5. 容器模型第一版只能粗估，尤其是深碗、液体、透明容器。
6. 无用户输入会降低高度估计上限，因此必须依赖类别先验和置信度表达。
7. 打印卡如果没有按 100% 比例打印，会造成系统性误差。
8. 筷子夹取、勺子舀取、叉子叉取动作通常持续时间短，纯低频采集可能漏掉关键帧，因此需要事件增强采样。
9. 餐具和手部会频繁遮挡食物，可能导致误判为食物消失或摄入，需要通过轨迹和时间窗口过滤。
10. 口部/脸部检测涉及隐私和视角限制，第一版不应强依赖口部识别。
11. 餐具上食物小块面积较小，分割误差对单次摄入克重影响较大，需要在报告中表达 `bite_weight_error_g`。

## 17. 待确认事项

以下事项不阻塞第一版开发，但需要后续产品或算法进一步确认：

1. 标定卡最终品牌硬件形态：硬卡、贴纸、餐垫、托盘标识或随身卡。
2. 是否需要在标定卡上加入二维码，承载设备绑定、用户 ID 或产品说明。
3. 是否需要支持多 marker 标定板，用于更准确的平面姿态估计。
4. 摄入完成是否需要用户最终确认，还是完全自动记录。
5. 容器库是否需要标准化，例如固定碗、餐盒、餐盘型号。
6. 是否需要使用手机 IMU、焦距、ARCore/ARKit 深度能力作为二期增强。
7. 是否允许在隐私合规前提下启用口部/脸部区域检测，用于提高 `intake_confirmed` 置信度。
8. 是否需要针对筷子、勺子、叉子分别训练专用检测模型。
9. 是否需要将标定卡做成餐垫、托盘贴纸或桌面固定标识，以提升餐具事件中的尺度稳定性。

## 18. 一期结论

第一版采用“自定义实体 ArUco 标定卡 + 真实尺度面积 + 食物高度先验 + 容器粗模型 + 餐具摄入事件 + 有效帧融合”的路线。

产品上不强制用户放置标定卡，但算法上严格区分：

```text
有标定卡：可进入 calibrated / approximate 估重链路
无标定卡：仅进入 rough 粗估链路
```

多帧优化不再以采集时长为核心，而以有效标定帧质量为核心。

同时，最终饮食记录不应只依赖碗盘中剩余量变化，而应优先累计用户通过筷子、勺子、叉子等餐具产生的 confirmed `IntakeEvent`。容器剩余量用于校验、补偿和异常检测。

该方案能够在不显著增加用户负担的前提下，解决现有算法缺少真实尺度参照、长时间帧叠加无法提升精度的问题，并为后续标准化品牌硬件、容器模型、餐具事件识别和真实摄入过程记录打下基础。
