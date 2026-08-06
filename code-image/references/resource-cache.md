# Code Image 资源记录约定

## 文件位置

所有运行时记录固定写入项目根目录：

```text
.code-image/resources.json
```

不得读取、创建或更新 `.codex/lanhu-resources.json`、`.codex/code-image-manifest.json` 或其他项目外缓存。写入时先在 `.code-image/` 内创建临时文件，再原子替换 `resources.json`。

## 文件格式

```json
{
  "version": 1,
  "resources": [
    {
      "identity": "app/src/main/res:app/src/main/res/mipmap-nodpi/Group 62.png:<sha256>",
      "originalPath": "app/src/main/res/mipmap-nodpi/Group 62.png",
      "originalName": "Group 62.png",
      "originalHash": "sha256...",
      "outputPath": "app/src/main/res/mipmap-nodpi/icon_report_home_group_62.png",
      "outputName": "icon_report_home_group_62.png",
      "composeFile": "app/src/main/java/com/example/report/ReportHomePage.kt",
      "resourceFamily": "app/src/main/res",
      "updatedAt": "2026-08-07T00:00:00+00:00"
    }
  ]
}
```

`composeFile` 在未提供 `--compose` 时为 `null`。`originalPath` 和 `originalName` 表示第一次处理时的输入，重复调用不得改写；`outputPath` 和 `outputName` 表示当前文件位置和名字。

## 查找规则

重复处理一张图片时按以下顺序匹配已有记录：

1. 当前输入路径等于 `outputPath`；或等于 `originalPath` 且 `originalHash` 与当前 Hash 一致。
2. 同一 `resourceFamily` 内只有一条记录的 `originalHash` 与当前 Hash 一致。

第二步命中多条记录时视为不同图片，创建独立记录，禁止自动合并。文件名冲突只检查同一资源族中的 `mipmap`、`mipmap-*` 目录，不重命名或写入其中的其他图片。
