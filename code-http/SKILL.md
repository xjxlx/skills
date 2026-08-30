---
name: code-http
description: "Use when Android/Kotlin 需要根据 .http 请求和真实接口响应或 JSON，在指定 ViewModel 中补齐 API、Bean、Flow 与调用方法。"
---

# code-http

根据 `.http` 请求与真实响应，为现有 Android/Kotlin 项目生成一条可编译的接口调用链：请求参数、ViewModel 方法、对外 Flow、响应 Bean 和 Retrofit API。核心原则是“响应证据决定 Bean 结构；项目现有代码决定接入方式”。

## 基础规范

- 每次调用开始先执行：
  `"${CODEX_HOME:-$HOME/.codex}/skills/github-manager/scripts/check_and_publish.sh"`。
  检测或自动发布失败时停止；有变化时等待发布成功并向用户说明。
- 必须遵循 `$skill-common` 的基础规范。任务完成并验证后调用 `$skill-common` 复盘；不要复制它的规则。
- 本技能只负责 `.http` 接口到 Android/Kotlin 调用链的接入，不顺手修复无关页面、重构网络层或生成测试工程。
- 保留用户已有修改，只编辑目标 ViewModel、对应 Bean 文件和实际 API 接口文件；发现范围外改动时先停下并报告。

## 输入与证据

必须确认以下输入：

1. `.http` 文件路径。用户点名接口描述或序号时只处理该请求；只给文件路径时，按描述块顺序处理全部不同接口。
2. 目标 ViewModel 路径。
3. 真实响应文本或 JSON 文件。响应可以是 HTTP 日志，需先去除响应头并解析 JSON body。

响应证据按以下顺序使用：用户明确提供的 JSON、与目标请求匹配的最新 `.idea/httpRequests/*.json`、用户粘贴的响应、在认证和环境均可用时实际运行请求。请求无法运行且没有响应文件时，停止并要求补充响应，不得凭接口名称编造字段。

处理前读取目标 ViewModel 全文、目标 ViewModel 所在 package 的同级 `bean` 目录、项目实际的 `ApiServiceKotlin` 或等价 API 接口、`BaseBuddyViewModel` 及一个最近的同类 ViewModel。Bean 路径严格从目标 ViewModel 的 package 推导，例如 `...compose.v2.V2ViewModel.kt` 对应 `...compose.v2.bean/`；不能根据接口现有调用方、页面路径或其他模块猜目录。确认 `mApi` 的真实声明、`getMap`/参数封装方式、Flow 类型和错误处理模式后再写代码。

`.http` 中完全相同的重复请求块只生成一次；service 相同但参数、描述或响应不同的块视为不同接口，按出现顺序使用版本后缀。描述相同且无法判断是否重复时，先比较请求字段和响应证据，仍不明确则停止并要求选择。

## 命名契约

### 方法名

1. 读取 `.http` 中 `service` 的完整值，例如 `App2022new.getCampHome`。
2. 取最后一个 `.` 后的片段；没有 `.` 时直接使用完整值。
3. 将 `_`、`-`、空格等分隔符转换为 lowerCamelCase，只把首个有效字母小写，保留已有的内部大小写。示例：
   `App2022new.getCampHome` → `getCampHome`，`App.App2022.GetBook` → `getBook`。
4. ViewModel 方法名、API 函数名和请求中的 `service` 语义保持一一对应；不要把服务名改成中文或自定义缩写。

### Flow 与 Bean 名

以方法名生成业务基名：只移除开头且后面紧跟大写字母的动作前缀 `get`、`fetch`、`query`、`load`、`list`；没有这些前缀时保留方法名。然后：

| service | ViewModel 方法 | 对外 Flow | Bean |
|---|---|---|---|
| `App2022new.getCampHome` | `getCampHome` | `campHomeFlow` | `CampHomeBean` |
| `App.App2022.GetBook` | `getBook` | `bookFlow` | `BookBean` |

Flow 默认遵循项目现有模式：`private val _campHomeFlow = MutableStateFlow<CampHomeBean?>(null)`，对外暴露 `val campHomeFlow = _campHomeFlow.asStateFlow()`。若同类接口使用 `SharedFlow` 或列表初始值，优先跟随同级代码。

如果目标 ViewModel 已存在相同方法名，依次使用 `V1`、`V2`……，并同步追加到 API 函数、Flow 和 Bean：
`getCampHomeV1`、`campHomeV1Flow`、`CampHomeV1Bean`。先检查 ViewModel、Bean 目录和 API 接口中的完整符号，不能只检查当前文件。

## 响应到 Bean

- 对常见响应 `{ "ret": 200, "data": ... }`，Bean 只描述 `data` 的内容，不把 `ret` 或 `data` 包装层重复建模；保持 `BuddyHttpResult<Bean>` 的项目解包方式。
- `data` 是对象时生成目标 Bean；嵌套对象和对象数组按同级 Bean 的写法生成嵌套 `data class` 或独立类。
- `data` 是数组时，Bean 表示数组元素，API 使用 `BuddyHttpResult<List<XxxBean>>`，Flow 使用列表类型并以 `emptyList()` 初始化；不要为数组额外包一层没有证据的响应类。
- `data` 是字符串、数字、布尔值或明确的 `null` 时，不创建虚假的 Bean。使用项目支持的原生类型；`data: null` 只能说明返回可为空，不能推断字段。
- 字段、层级、集合和类型必须来自完整响应。出现 `null` 或同一字段类型不一致时使用可空或项目已有的兼容类型，并记录判断依据。
- 优先保持当前项目的 JSON 字段命名约定。项目已有 Bean 使用 `snake_case` 属性时不要擅自改成 camelCase；若项目使用 `@SerializedName`，沿用该风格。
- 不用默认值或“常见用户字段”掩盖缺失响应；默认值只有在同级 Bean 已明确采用该约定时才使用。
- Bean 文件必须保存到目标 ViewModel package 下的 `bean` 子目录，package 声明、import 和文件路径必须三者一致；即使 API 已在别的模块存在相似 Bean，也不能跨目录复用或迁移，除非用户明确要求。

## 生成调用链

### 1. 解析请求参数

- 保留服务端字段名，例如 `unid`、`term_suiji`、`suiji`，只将 Kotlin 参数变量写成项目惯用的驼峰名，例如 `unId`、`termSuiJi`。
- `{{variable}}` 形式的变量通常生成方法参数；请求中的固定字面量按同级 ViewModel 约定处理，不要把用户身份、令牌或环境值硬编码进代码。
- `map.setParameter("service", "原始 service")` 必须使用 `.http` 中的精确值，大小写和点号都不能丢失。
- 不要根据响应字段反推请求参数；请求字段以选中的 `.http` 片段为准。

### 2. 修改 API 接口

在项目真实的 API 接口中，按邻近代码的顺序和注解风格添加对应函数。典型形式为：

```kotlin
@FormUrlEncoded
@POST(BASE_URL)
suspend fun getCampHome(
    @FieldMap map: MutableMap<String, Any>
): BuddyHttpResult<CampHomeBean>
```

补充正确 import，使用 `BuddyHttpResult<Bean>`、`BuddyHttpResult<List<Bean>>` 或响应实际的原生类型。不要在 `BaseBuddyViewModel` 中重复声明 `mApi`。

### 3. 修改 ViewModel

沿用目标 ViewModel 的协程和错误处理方式。对 `BaseBuddyViewModel` 的常见接入形态是：

```kotlin
private val _campHomeFlow = MutableStateFlow<CampHomeBean?>(null)
val campHomeFlow = _campHomeFlow.asStateFlow()

fun getCampHome(unId: String, termSuiJi: String) {
    val map = getMap("getCampHome")
    map.setParameter("unid", unId)
    map.setParameter("term_suiji", termSuiJi)
    map.setParameter("service", "App2022new.getCampHome")
    viewModelScope.launch {
        BuddyClient.http(
            { mApi.getCampHome(it) },
            map,
            onSuccess = { _campHomeFlow.value = it },
            onFailure = { LogUtil.e("getCampHome error:${it.message}") },
        )
    }
}
```

根据实际项目调整 `onSuccess`、`onFailure` 和参数容器，但必须满足：请求字段完整、调用 API 函数正确、成功结果写入对应 Flow。方法名重复时所有引用必须使用同一版本后缀。

## 验证与停止条件

生成后依次完成：

1. 检查 `git diff --check`、未使用 import、package 路径和 Bean/API/Flow 的类型闭环。
2. 检查只修改了目标 ViewModel、对应 Bean、API 接口以及编译所必需的 import；发现格式化工具产生无关变更时清理它们。
3. 使用项目已有的格式化和 Android CLI/Gradle 编译任务。BdEnglish 项目优先验证 `./gradlew :app:spotlessApply :app:compileDebugKotlin`，再运行 `./gradlew :app:spotlessCheck`；若项目变体不同，使用实际存在的目标任务。
4. 编译失败时区分本次新增错误和工作区原有错误，报告首个可定位错误及证据；不能用“未执行编译”宣称完成。

遇到以下情况停止生成并说明原因：响应缺失或 `data:null` 却要求生成未知 Bean；重复请求块无法区分；目标 API 接口无法定位；命名冲突无法通过版本后缀消解；响应结构与现有 Bean 冲突且没有明确兼容策略。

## 常见错误

| 错误 | 修正 |
|---|---|
| 把 `ret`、`data` 再写进业务 Bean | 只建模 `data` payload |
| `data:null` 时补出 ProfileBean 字段 | 要求对象响应，或使用已有且有证据的 Bean |
| 只给 ViewModel 加方法，忘记 API 或 Flow | 以“请求参数 → API → Bean → Flow”闭环检查 |
| `getCampHome` 生成成 `getCampHomeFlow` 或 Bean 带 `get` | 按命名表使用 `campHomeFlow`、`CampHomeBean` |
| Kotlin 参数名替换了服务端 key | 变量名可驼峰，`setParameter` 的 key 必须原样保留 |
| 重复接口只改方法名 | V1/V2 必须同步到 API、Flow、Bean 和全部引用 |
| 为了编译顺手修改页面或测试 | 还原越界改动，只保留接口调用链所需文件 |

完成代码验证后调用 `$skill-common` 复盘；没有新的通用证据时不扩张本技能规则。
