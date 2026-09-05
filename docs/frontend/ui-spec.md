# 页面与交互规格

## 技术基线

- 服务端渲染 HTML 或静态 HTML 均可。
- Bootstrap 5.3 提供栅格、表单、响应式和基础交互。
- 第一版继续使用原生 JavaScript，不要求 React/Vue。
- 项目 CSS 负责工作台的信息密度和状态层级。
- 不使用 jQuery。

## 页面结构

桌面端采用固定顶部摘要、左侧标签队列、右侧处理区和底部操作栏。

```text
┌ 漫画录入 / Hitomi #123456                         [返回]
│ 标题 · 作者 · 来源 · 18/23 标签已映射
├────────────────────┬─────────────────────────────────────┐
│ 标签队列            │ 当前 SpecificTag                    │
│                    │                                     │
│ ✓ 已映射      18    │ origin_name: glasses                │
│ ◉ 推荐候选     2    │ group: tags                         │
│ ! 待人工处理   3    │ tag_sex: female                     │
│ × 请求失败     0    │ URL: ...                            │
│                    │                                     │
│ [搜索] [状态筛选]   │ TagGroup: [ Tag ▼ ]                 │
│                    │                                     │
│ > glasses          │ GenericTag 候选                      │
│   artist cg        │ ○ tag / glasses                      │
│   comiket 99       │ ○ property / glasses                 │
│                    │ ○ 搜索其他标签                       │
│                    │ ○ 创建新标签                         │
│                    │                                     │
│                    │       [采用并处理下一个]              │
├────────────────────┴─────────────────────────────────────┤
│ [查看原始 metadata]       剩余 3 个       [录入漫画]      │
└──────────────────────────────────────────────────────────┘
```

Bootstrap 栅格建议：

```html
<div class="container-fluid">
  <div class="row">
    <aside class="col-md-4 col-xl-3"></aside>
    <main class="col-md-8 col-xl-9"></main>
  </div>
</div>
```

不要将所有区域都做成嵌套 Card。主要依靠边框、留白、标题层级和背景色区分区域。

## 顶部漫画摘要

显示：

- Comic ID
- 来源站点与来源 document ID
- 标题
- 作者
- 已映射数量与总数
- 当前页面状态

由前端按需组合 Comic、标签关系和 DMB 来源数据；预览接口只返回 Comic 原模型。

组件建议：

- `breadcrumb`：返回列表或来源文档。
- `progress`：映射完成比例。
- `badge`：来源站点。
- `accordion`：原始 source metadata。

漫画已存在时，使用明确的 `alert-info`：

> 该漫画已经录入。

提供“查看已有漫画”和“返回”按钮，不自动跳转。

## 左侧标签队列

使用 `list-group`，每项至少显示：

- `origin_name`
- 原始 Hitomi group
- tag sex（存在时）
- 状态图标和文字

状态不能只靠颜色表达：

| 状态 | 文案 | 建议颜色 |
|---|---|---|
| `loading` | 查询中 | secondary |
| `resolved` | 已映射 | success |
| `recommended` | 有推荐 | warning |
| `unresolved` | 待处理 | danger |
| `saving` | 保存中 | primary |
| `error` | 请求失败 | danger |

支持：

- 按名称搜索。
- 按状态筛选。
- 按原始 group 筛选。
- “只看待处理”快捷开关。

选中项必须同时使用左边框和 `aria-current="true"`，不能只改变背景色。

## SpecificTag 信息区

始终展示完整的决策依据：

- site
- origin_name
- 原始 group
- tag_sex
- URL
- 其他站点特有字段

URL 使用新标签页打开，并增加 `rel="noopener noreferrer"`。

完整 JSON 放在折叠区中，用等宽字体展示。普通流程不直接编辑 SpecificTag metadata。

## TagGroup 选择

使用 `form-select`，选项来自 `GET /api/tags/groups`。

选择框结合原始 SpecificTag 信息供用户确定分类，不依赖 preview 附加的推断字段。
尚未确定分类时提示用户选择，不自动归入 Tag。

在用户选定 TagGroup 前，禁用 GenericTag 创建按钮。

## GenericTag 候选

候选较少时使用单选 `list-group`；候选较多时使用紧凑表格。

每个候选显示：

- `tag_group / name`
- 关联的证据 SpecificTag 数量
- 展开证据按钮

证据区展示来源 group、sex、URL 和 site。多个证据指向同一 GenericTag 时不得
重复显示候选单选项。

三个操作模式使用 `nav-tabs` 或分段按钮：

1. 推荐候选
2. 搜索已有标签
3. 创建新标签

切换模式不立即写数据库。

## 创建 GenericTag

表单字段：

- TagGroup：默认采用当前选择，只读或同步修改。
- Name：默认 `origin_name`，允许编辑。

提交创建前先执行 exact GenericTag 查询，以减少不必要的 `409`。即便预查为空，
仍必须正确处理并发导致的 `GENERIC_TAG_EXISTS`。

创建成功后不要停留在“创建成功”中间页，直接继续创建 SpecificTag 映射。

## 底部操作栏

使用自定义 sticky footer，而不是全屏 modal：

- 左侧：“查看 metadata”或“返回”。
- 中间：映射进度和剩余数量。
- 右侧：“采用并处理下一个”或“录入漫画”。

“录入漫画”按钮只有全部标签已解析时启用。禁用时在相邻文本中说明原因，
不能只依赖 disabled tooltip。

## 最终复核

最终复核可以使用主页面状态或大型 `offcanvas`。不推荐普通居中 modal，因为标签
汇总可能很长。

按 GenericTag group 分区展示最终结果。新建记录使用“本次新增”标记，但不要将
新建和复用拆成两套互不相干的列表。

## 成功与失败反馈

- 单个映射保存成功：行内状态变化，不弹 Toast。
- 可恢复网络错误：行内错误加“重试”。
- 全局 commit 成功：独立成功状态，提供“查看漫画”和“处理下一部”。
- 服务端数据冲突：使用页面内 `alert`，并保留用户当前查看位置。
- 非关键提示：Bootstrap Toast。

## 响应式

该工具以桌面管理场景为主。

在小于 `md` 的屏幕：

- 左侧队列移入 `offcanvas`。
- 主区一次只显示一个 SpecificTag。
- 底部操作栏保持 sticky。
- 候选表格转换为纵向 list-group。

不要在移动端同时显示队列、详情和候选三列。

## 可访问性

- 所有输入都有可见 `label`。
- 状态变化通过 `aria-live="polite"` 通知。
- 错误与输入使用 `aria-describedby` 关联。
- 单选候选使用真实 `input[type=radio]`。
- 支持键盘 Tab 顺序完成整个映射流程。
- 图标必须配套文字或 `aria-label`。
