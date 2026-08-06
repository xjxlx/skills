# Code Image 资源记录约定

## 文件位置

运行记录固定写入：

```text
<project>/.code-image/resources.json
```

除 ZIP 按约定解压到 `~/Downloads/` 外，不得创建 `.code-image/` 之外的缓存或映射。JSON 写入时只在 `.code-image/` 内创建临时文件，再原子替换 `resources.json`。

## 文件格式

```json
{
  "version": 1,
  "resources": [
    {
      "identity": "/Users/name/Downloads/Group 62.png:<sha256>",
      "originalPath": "/Users/name/Downloads/Group 62.png",
      "originalName": "Group 62.png",
      "originalHash": "sha256...",
      "outputPath": "app/src/main/res/mipmap-xxhdpi/icon_report_home_group_62.png",
      "outputName": "icon_report_home_group_62.png",
      "composeFile": "app/src/main/java/com/example/report/ReportHomePage.kt"
    }
  ]
}
```

`composeFile` 未提供时为 `null`。不记录 `resourceFamily` 或 `updatedAt`；目标目录已经由 `outputPath` 表达。

ZIP 图片的 `originalPath` 是下载目录内的解压后文件路径，`outputPath` 则是其对应的项目 `mipmap` 目录路径。

ZIP 不含任何 `mipmap` 或 `mipmap-*` 目录下的图片时，不创建下载目录、不写入 JSON，也不作为 ZIP 处理；应改为传入一张实际图片使用 `--image`。

## 查找和冲突规则

重复导入时，只有“原始路径加相同 Hash”或“输出路径加相同 Hash”才复用记录。Hash 变化时保留旧记录并生成新名称，禁止覆盖旧输出。

同一目标目录中名称被占用时按 `_1`、`_2`、`_3` 递增。不同密度目录允许保留同一个资源名。
