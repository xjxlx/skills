# Code Image 资源记录约定

## 文件位置

每个来源身份维护一份可复用记录：

```text
<project>/.code-image/<来源名>-<完整来源MD5>.resources.json
```

ZIP 的来源名和 Hash 取 ZIP 本身，单图取图片本身；完整 MD5 避免短前缀碰撞。同一来源身份始终复用一份记录。ZIP 原始文件只在系统临时目录中短暂存在，以 `.extraction.json` 绑定本次解压文件的路径、大小和 Hash；导入结束后临时目录自动清理，项目 `.code-image/` 不保存原始图片。

## 文件格式

```json
{
  "version": 2,
  "resources": [
    {
      "identity": "input/Group 62.png:<md5>:feature/src/main/res/mipmap-xxhdpi",
      "originalPath": "input/Group 62.png",
      "originalName": "Group 62.png",
      "originalHash": "md5...",
      "outputPath": "feature/src/main/res/mipmap-xxhdpi/icon_report_home_group.png",
      "outputName": "icon_report_home_group.png",
      "namingVersion": 3,
      "composeFile": "feature/src/main/java/com/example/report/ReportHomePage.kt"
    }
  ]
}
```

`composeFile` 未提供时为 `null`。身份包含目标资源目录，使同一来源可同时用于多个模块而不迁移或删除旧模块资源。不记录 `resourceFamily` 或 `updatedAt`；目标目录已经由 `outputPath` 表达。

ZIP 图片的 `originalPath` 使用稳定的 `<ZIP文件名>!/<ZIP内部路径>` 格式，例如 `L6.zip!/mipmap-xxhdpi/矩形.png`；`outputPath` 是目标模块对应的 `mipmap` 路径。蓝湖协调器逐图调用时，ZIP 内图片可共用显式来源清单；`--resources-file` 兼容 6 位或完整 MD5 文件名，但路径必须直属项目 `.code-image/`。

ZIP 导入生成名称时使用 ZIP 文件名作为前缀：`L6.zip` 中的 `矩形备份 4.png` 在 `mipmap-xxhdpi` 目录输出为 `icon_l6_rectangle.png`。中文优先转换为语义英文，未知中文使用拼音；不使用 MD5 或 `image_` 作为名称兜底。ZIP 内不同密度目录分别映射到项目对应的同名密度目录。

ZIP 不含任何 `mipmap` 或 `mipmap-*` 目录下的图片时，不创建临时解压内容、不写入 JSON，也不作为 ZIP 处理；应改为传入一张实际图片使用 `--image`。

## 查找和冲突规则

重复导入先按“原始路径、内容 Hash、目标目录”匹配；同一来源清单内的不同 ZIP 条目再按“相同内容 Hash、相同目标目录”匹配。输出文件存在且 Hash 一致时不复制、不改 mtime；丢失或被篡改时按当前命名版本原子恢复。旧命名版本记录重新导入时按当前规则迁移。不同来源或模块记录互不迁移、删除；目标名被其他内容占用时生成新名称。

同一目标目录中名称被占用时按 `_1`、`_2`、`_3` 递增。ZIP 内同一密度目录发生规范化重名时同样递增；不同密度目录允许保留同一个资源名。
