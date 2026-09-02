# Code Image 资源记录约定

## 文件位置

项目只维护一份最近导入记录：

```text
<project>/.code-image/image.json
```

每次成功 `--apply` 原子覆盖 `image.json`，文件内容只对应本次导入；旧版按来源生成的 `*.resources.json` 和 `resources.json` 会在成功写入后清理。图片输出文件不随清单删除。ZIP 原始文件只在系统临时目录中短暂存在，以 `.extraction.json` 绑定本次解压文件的路径、大小和 Hash；导入结束后临时目录自动清理，项目 `.code-image/` 不保存原始图片。

## 文件格式

```json
{
  "version": 2,
  "resources": [
    {
      "originalPath": "input/Group 62.png",
      "originalName": "Group 62.png",
      "originalHash": "md5...",
      "outputPath": "feature/src/main/res/mipmap-xxhdpi/icon_report_home_group.png",
      "outputName": "icon_report_home_group.png"
    }
  ]
}
```

每项只保留五个跨工具需要的字段：`originalPath`、`originalName`、`originalHash`、`outputPath`、`outputName`。完整 `originalHash` 用于处理当前批次内的 ZIP 改名和与 `code-html-compose` 匹配；`outputPath` 同时限定目标模块和密度目录。不再写入 `identity`、`composeFile` 或 `namingVersion`；旧字段可被兼容读取，重新 apply 时清理。不记录 `resourceFamily` 或 `updatedAt`。

ZIP 图片的 `originalPath` 使用稳定的 `<ZIP文件名>!/<ZIP内部路径>` 格式，例如 `L6.zip!/mipmap-xxhdpi/矩形.png`；`outputPath` 是目标模块对应的 `mipmap` 路径。协调脚本必须复用项目 `.code-image/image.json`，不能创建按来源命名的清单。

ZIP 导入生成名称时使用 ZIP 文件名作为前缀：`L6.zip` 中的 `矩形备份 4.png` 在 `mipmap-xxhdpi` 目录输出为 `icon_l6_rectangle.png`。中文优先转换为语义英文，未知中文使用拼音；不使用 MD5 或 `image_` 作为名称兜底。ZIP 内不同密度目录分别映射到项目对应的同名密度目录。

ZIP 不含任何 `mipmap` 或 `mipmap-*` 目录下的图片时，不创建临时解压内容、不写入 JSON，也不作为 ZIP 处理；应改为传入一张实际图片使用 `--image`。

## 查找和冲突规则

同一批次内重复导入先按“原始路径、内容 Hash、目标目录”匹配；同一 ZIP 条目再按“相同内容 Hash、相同目标目录”匹配。输出文件存在且 Hash 一致时不复制、不改 mtime；丢失或被篡改时按记录中的 `outputName` 原子恢复。不同批次只覆盖 `image.json` 的记录，不迁移或删除旧图片；目标名被其他内容占用时生成新名称。

同一目标目录中名称被占用时按 `_1`、`_2`、`_3` 递增。ZIP 内同一密度目录发生规范化重名时同样递增；不同密度目录允许保留同一个资源名。
