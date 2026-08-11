# Code Image 资源记录约定

## 文件位置

每个来源身份维护一份可复用记录：

```text
<project>/.code-image/<来源名>-<完整来源MD5>.resources.json
```

ZIP 的来源名和 Hash 取 ZIP 本身，单图取图片本身；完整 MD5 避免短前缀碰撞。同一来源身份始终复用一份记录。ZIP 私有缓存位于 `<project>/.code-image/extracted/<来源名>-<完整MD5>/`，以 `.extraction.json` 绑定每个文件的路径、大小和 Hash；JSON 和图片均用同目录临时文件原子替换。

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
      "outputPath": "feature/src/main/res/mipmap-xxhdpi/icon_report_home_group_62.png",
      "outputName": "icon_report_home_group_62.png",
      "composeFile": "feature/src/main/java/com/example/report/ReportHomePage.kt"
    }
  ]
}
```

`composeFile` 未提供时为 `null`。身份包含目标资源目录，使同一来源可同时用于多个模块而不迁移或删除旧模块资源。不记录 `resourceFamily` 或 `updatedAt`；目标目录已经由 `outputPath` 表达。

ZIP 图片的 `originalPath` 是项目私有解压目录内路径，`outputPath` 是目标模块对应的 `mipmap` 路径。蓝湖协调器逐图调用时，ZIP 内图片可共用显式来源清单；`--resources-file` 兼容 6 位或完整 MD5 文件名，但路径必须直属项目 `.code-image/`。

ZIP 不含任何 `mipmap` 或 `mipmap-*` 目录下的图片时，不创建解压目录、不写入 JSON，也不作为 ZIP 处理；应改为传入一张实际图片使用 `--image`。

## 查找和冲突规则

重复导入先按“原始路径、内容 Hash、目标目录”匹配；同一来源清单内的不同 ZIP 条目再按“相同内容 Hash、相同目标目录”匹配。输出文件存在且 Hash 一致时不复制、不改 mtime；丢失或被篡改时按记录原子恢复。不同来源或模块记录互不迁移、删除；目标名被其他内容占用时生成新名称。

同一目标目录中名称被占用时按 `_1`、`_2`、`_3` 递增。不同密度目录允许保留同一个资源名。
