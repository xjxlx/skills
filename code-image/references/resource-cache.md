# Code Image 资源缓存约定

## 路径解析

支持以下输入：

| 用户输入 | 解析方式 |
|---|---|
| `res/mipmap` | 项目根目录下的 `res/mipmap`，再尝试 `app/src/main/res/mipmap` |
| `res.mipmap` | 转换为 `res/mipmap` 后按上面的顺序查找 |
| `res.layouts.report.mipmap` | 转换为 `res/layouts/report/mipmap` 后按上面的顺序查找 |
| 绝对路径 | 直接使用 |

路径末尾为 `mipmap` 时，同时扫描同级的 `mipmap-xhdpi`、`mipmap-xxhdpi`、`mipmap-xxxhdpi` 等目录。不同密度目录属于同一资源族，必须共享资源文件名。

## 资源身份

资源身份按以下优先级确定：

1. 既有 manifest 中匹配的当前路径或输出路径。
2. 既有 manifest 中相同 Hash 且属于同一资源族的记录。
3. 当前资源族路径和原始文件名。

Hash 用于识别原始文件被改名的情况，不用于把不同资源自动合并。即使两个图片内容相同，也默认保留两个资源记录。

## `lanhu-resources.json`

该文件保持 `code-compose` 可直接读取的简单映射：

```json
{
  "Group 62.png": "icon_reporthomev2layoutgroup62.png",
  "res/layouts/report/mipmap-xhdpi/Group 63.png": "icon_reporthomev2layoutgroup63.png"
}
```

原始名称唯一时使用文件名作为键；同名资源出现在不同资源族时，使用资源族路径加文件名作为键。

## `code-image-manifest.json`

完整记录示例：

```json
{
  "version": 1,
  "resources": [
    {
      "identity": "res/layouts/report:Group 62.png",
      "originalName": "Group 62.png",
      "outputName": "icon_reporthomev2layoutgroup62.png",
      "currentPath": "app/src/main/res/layouts/report/mipmap-xhdpi/icon_reporthomev2layoutgroup62.png",
      "resourceFamily": "app/src/main/res/layouts/report",
      "composeFile": "app/src/main/java/com/jollyeng/www/compose/ui/activity/report/ReportHomeV2Layout.kt",
      "hash": "sha256..."
    }
  ]
}
```

原文件名变化但 Hash 未变化时，更新同一条记录的 `originalName`、`outputName` 和路径；Hash 变化时保留旧记录并创建新资源记录。
