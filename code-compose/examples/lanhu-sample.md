# 示例：蓝湖信息 → Compose 代码

## 蓝湖复制内容（输入）

```text
卡片 320×120
圆角 12
背景 #FFFFFF
标题：今日学习 16sp 粗体 #1A1A1A
副标题：已完成 3/5 课 12sp #666666
内边距 16
```

蓝湖实际复制格式不固定，解析时不要求固定格式，按字段提取。

## 生成结果（输出）

```kotlin
@Composable
fun StudyProgressCard(
    title: String,
    subtitle: String,
    modifier: Modifier = Modifier,
) {
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(120.dp)
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surface)
            .padding(16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text = title,
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onSurface,
            )
            Spacer(modifier = Modifier.height(4.dp))
            Text(
                text = subtitle,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
    }
}
```

实际输出必须按项目约定替换主题引用（colorScheme/Typography 语义、spacing 体系、组件命名）；此例仅演示结构与映射过程。
