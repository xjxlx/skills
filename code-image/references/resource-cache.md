# Code Image 资源记录约定

## 文件位置

每个来源身份维护一份可复用记录：

```text
<project>/.code-image/<来源名>-<来源MD5前6位>.resources.json
```

例如：`<project>/.code-image/1600-xxxxxx.resources.json`。ZIP 的来源名和 Hash 取 ZIP 本身，单图取图片本身；同一来源身份始终复用这一份记录。除 ZIP 按约定解压到 `~/Downloads/` 外，不得创建 `.code-image/` 之外的缓存或映射。JSON 写入时只在 `.code-image/` 内创建临时文件，再原子替换该来源清单。

## 文件格式

```json
{
  "version": 1,
  "resources": [
    {
      "identity": "/Users/name/Downloads/Group 62.png:<md5>",
      "originalPath": "/Users/name/Downloads/Group 62.png",
      "originalName": "Group 62.png",
      "originalHash": "md5...",
      "outputPath": "app/src/main/res/mipmap-xxhdpi/icon_report_home_group_62.png",
      "outputName": "icon_report_home_group_62.png",
      "composeFile": "app/src/main/java/com/example/report/ReportHomePage.kt"
    }
  ]
}
```

`composeFile` 未提供时为 `null`。不记录 `resourceFamily` 或 `updatedAt`；目标目录已经由 `outputPath` 表达。

ZIP 图片的 `originalPath` 是下载目录内的解压后文件路径，`outputPath` 则是其对应的项目 `mipmap` 目录路径。蓝湖协调器逐图调用时，ZIP 内全部图片共用同一个 ZIP 身份清单。

ZIP 不含任何 `mipmap` 或 `mipmap-*` 目录下的图片时，不创建下载目录、不写入 JSON，也不作为 ZIP 处理；应改为传入一张实际图片使用 `--image`。

## 查找和冲突规则

重复导入先按“原始路径加相同 Hash”匹配；同一来源清单内的不同 ZIP 条目再按“相同内容 Hash 加相同目标密度”匹配。命中后直接使用记录的 `outputPath` 和 `outputName`，不复制、不比较目标文件内容，也不追加 `_1`；清单只保留首个条目的规范记录。不同来源清单互不读取、迁移或删除；目标名被其他来源占用时生成新名称。

同一目标目录中名称被占用时按 `_1`、`_2`、`_3` 递增。不同密度目录允许保留同一个资源名。
