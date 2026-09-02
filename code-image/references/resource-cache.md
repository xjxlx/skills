# Code Image 资源记录约定

## 文件位置

项目维护一份跨模块、跨批次的累计图片索引：

```text
<project>/.code-image/image.json
```

成功 `--apply` 会扫描所有 Android 模块的 `src/main/res`，将当前存在的图片合并进 `image.json` 并原子写回；同路径内容变化会更新记录，已删除文件会移除记录，多路径相同 MD5 会分别保留。旧版来源清单在写入成功后清理，图片输出文件不随清单删除。ZIP 原始文件只在系统临时目录中短暂存在，以 `.extraction.json` 绑定本次解压文件的路径、大小和 Hash；导入结束后临时目录自动清理，项目 `.code-image/` 不保存原始图片。

可用 `python3 scripts/normalize_images.py --scan --project-root <项目根目录> --apply` 单独建立或刷新目录；单独扫描不会复制、改名或删除项目图片。

## 文件格式

```json
{
  "version": 3,
  "resources": [
    {
      "md5": "49fbd5d43e7479e3177936fea5ea29ec",
      "identifier": "feature/src/main/res/mipmap-xxhdpi/icon_report_home_group.png-49fbd5d43e7479e3177936fea5ea29ec",
      "path": "feature/src/main/res/mipmap-xxhdpi/icon_report_home_group.png",
      "name": "icon_report_home_group.png",
      "source": "L6.zip!/mipmap-xxhdpi/Group 62.png"
    }
  ]
}
```

核心字段是 `md5`、`identifier`、`path`、`name`。`identifier` 为 `path-md5`，用于区分同一内容在不同项目路径的记录；`path` 同时限定模块和密度目录。ZIP 记录可用 `source` 追溯设计包来源；单图记录不强制写入 `source`。旧版 `originalHash`、`outputPath`、`outputName` 可被兼容读取，重新 apply 时转换；不记录 `resourceFamily` 或 `updatedAt`。

ZIP 图片的 `source` 使用稳定的 `<ZIP文件名>!/<ZIP内部路径>` 格式，例如 `L6.zip!/mipmap-xxhdpi/矩形.png`；`path` 是目标模块对应的 `mipmap` 路径。协调脚本统一写入项目级 `image.json`，不创建按来源拆分的清单。

ZIP 导入生成名称时使用 ZIP 文件名作为前缀：`L6.zip` 中的 `矩形备份 4.png` 在 `mipmap-xxhdpi` 目录输出为 `icon_l6_rectangle.png`。中文优先转换为语义英文，未知中文使用拼音；不使用 MD5 或 `image_` 作为名称兜底。ZIP 内不同密度目录分别映射到项目对应的同名密度目录。

ZIP 不含任何 `mipmap` 或 `mipmap-*` 目录下的图片时，不创建临时解压内容、不写入 JSON，也不作为 ZIP 处理；应改为传入一张实际图片使用 `--image`。

## 查找和冲突规则

重复导入先按“来源路径、内容 Hash、目标目录”匹配；累计 `image.json` 内再按“相同内容 Hash、相同目标目录”复用。输出文件存在且 Hash 一致时不复制、不改 mtime；丢失或被篡改时按记录中的 `name` 原子恢复。清单更新不会删除已存在的输出图片；目标名被其他内容占用时生成新名称。扫描发现项目文件被删除时才移除对应清单记录。

同一目标目录中名称被占用时按 `_1`、`_2`、`_3` 递增。ZIP 内同一密度目录发生规范化重名时同样递增；不同密度目录允许保留同一个资源名。
