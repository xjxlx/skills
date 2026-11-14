# 生产级 Compose 适配

该文件用于生成页面与现有项目组件、状态和测试宿主的衔接。

## 页面入口

- Activity 负责设置窗口、全屏和一次 `BaseV3Page` 包装。
- 页面入口 Composable 接收业务状态、列表数据和回调。
- 不在纯视觉区域函数中发起网络请求或持有页面级副作用。
- 使用稳定业务 key 启动 `LaunchedEffect`，Flow 收集放在页面入口。

## 尺寸与锚点

- 生成页面内使用 `667×375dp` 设计坐标。
- 页面不进行第二层窗口缩放。
- 固定区域可用 `ConstraintLayout`、Guideline 或经过验证的固定尺寸。
- 连续内容优先使用 Row/Column/weight/spacedBy。
- 图片、背景和卡片有稳定比例时使用 `aspectRatio`。
- 只有局部光学修正才能使用 offset，整页 offset 或缩放不可接受。

## 文本与图片

- 文本默认使用项目 `TextItem`。
- 图片默认使用 `ImageItem(ImageParameter(...))`。
- Material3 `Text` 仅用于项目 TextItem 无法表达的文字装饰；其他 Material3 组件按业务需要复用。
- 纯文字默认由测量决定宽高；固定视觉盒必须说明设计原因。
- 出现底部裁切时检查父容器剩余高度、TextLayoutResult、行高和字体 padding，不只移动下方元素。

## 列表

- 重复项按数据类、列表和单一 item Composable 生成。
- 相同外框和公共槽位是列表判断依据，不受单张卡片内部状态差异影响。
- 横向或纵向 viewport 使用 Lazy 容器；尾项裁切由容器完成。
- 列表状态与滚动位置分开保存。

## Dialog、Popup 与状态

- Dialog 使用项目已有宿主。
- 锚点弹窗使用项目已有 PopupPositionProvider 或等价实现。
- 可见性、选中项、关闭和筛选结果由同一状态源驱动。
- 动态比例先清洗为有效范围，避免 NaN、负尺寸和越界。

## 验收与正式集成

- 测试阶段保留 `e<domIndex>` 标签用于边界校验。
- 正式业务整合时只保留有价值的语义标签和无障碍标记。
- 页面状态变化后同时复核内容结果和固定区域 bounds。
- 未通过统一 95% 验收时不得宣称完成。
