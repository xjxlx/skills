# BdEnglish Compose 约定

> 由 code-compose 维护，最后更新：2026-08-02
> 来源标记：用户确认 / 源码证据 / 编译修复

## 基础信息

- 项目名：
- 设计稿基准：
- Compose 源码目录：
- 编译验证命令：

## 颜色

## 字体

## 间距与尺寸

## 组件

## 适配

## 命名与结构

## 其他

## 设计稿

- 2026-08-02: 报告页设计稿为 812x375 横屏，1dp = 1px 设计像素（ReportHomeV2Layout Preview widthDp=812 heightDp=375）（来源：源码证据）

## 目录与命名

- 2026-08-02: 报告页布局放 app/src/main/java/com/jollyeng/www/compose/ui/activity/report，页面入口 ReportHomeActivity，布局文件 XxxLayout.kt（来源：源码证据）

## 编译

- 2026-08-02: 验证命令：./gradlew :app:compileDebugKotlin（来源：编译验证）

## 常用组件

- 2026-08-02: 图片用 ImageItem/ImageParameter（Int=本地资源，String=URL）；百分比定位用 ConstraintLayout+Guideline；图片资源位于 app/src/main/res/layouts/v2/report/mipmap-*（来源：源码证据）

## 资源缓存

- 2026-08-02: 蓝湖资源缓存文件为项目根 .codex/lanhu-resources.json，缺失资源先同尺寸空白占位（来源：用户确认）
