# 前端状态与异常处理

## 页面状态

原生 JavaScript 第一版建议维护一个单一页面状态对象：

```js
const state = {
  phase: 'loading',
  comicId: null,
  groups: [],
  preview: null,
  sourceRevision: null, // 来自 preview 的 ETag 响应头，不在 Comic 模型中
  tagItems: [],
  activeIndex: null,
  pendingRequestCount: 0,
  sessionCreatedGenericTags: [],
  sessionCreatedSpecificTags: [],
  globalError: null
};
```

`phase` 可取：

```text
loading
resolving
ready-to-commit
committing
success
already-exists
fatal-error
```

## 单个标签状态

```js
{
  specificTag: {},
  status: 'loading',
  exactMapping: null,
  candidates: [],
  selectedGroup: null,
  selectedGenericTag: null,
  error: null
}
```

`status`：

```text
loading
resolved
recommended
unresolved
saving
error
```

不要把 DOM 当作权威状态。每次 API 响应先更新 state，再由统一 render 函数更新
对应区域。

## 派生状态

以下状态不单独存储，由 `tagItems` 计算：

```js
const unresolvedCount = tagItems.filter(
  item => item.status !== 'resolved'
).length;

const canCommit =
  unresolvedCount === 0 &&
  pendingRequestCount === 0 &&
  phase === 'resolving';
```

避免同时维护 `resolvedCount`、`unresolvedCount` 和每行状态造成不一致。

## 请求并发

preview 后的 exact 查询采用有限并发，不使用无上限 `Promise.all()`。

建议：

- 同时最多 6 个 SpecificTag 查询。
- GenericTag 搜索输入使用 250–350ms debounce。
- 新搜索开始时通过 `AbortController` 取消旧请求。
- 写请求期间禁用当前标签的所有映射操作。
- Comic commit 期间禁用全页面写操作。

## 请求去重

同一 preview 中可能出现重复 SpecificTag。前端可以按服务端返回对象的稳定序列化
结果去重查询，但不得以去重结果改变 Comic 的原始标签列表。

即使前端做了去重，服务端 commit 仍需独立验证。

## 错误处理

### 网络错误

保留用户当前状态，只将相关标签标为 `error`。提供单行重试，不重新加载整个页面。

### `GENERIC_TAG_EXISTS`

用提交的 tag_group 和 name 精确查询 GenericTag ID，按需读取详情，再继续创建映射。

### `SPECIFIC_TAG_MAPPING_CONFLICT`

停止当前保存，重新执行该标签的 exact 查询取得 ID，再读取 `/generic` 关系：

- 如果已经映射到用户刚选择的 GenericTag，视为成功。
- 如果映射到其他 GenericTag，显示冲突双方，不自动覆盖。

### `META_SCHEMA_VIOLATION`

该错误不能由普通用户在页面中修复。阻断当前标签，展示 site、origin_name、
服务端 schema hash 和模型 schema hash，并要求维护者介入。

### `SOURCE_META_CHANGED`

Comic commit 收到该错误后：

1. 清除当前 preview 和本地标签状态。
2. 重新调用 preview。
3. 重新执行 exact 查询。
4. 提示用户来源 metadata 已更新。

已写入数据库的 Tag 映射不会回滚，并会在新的 exact 查询中自然复用。

### `UNMAPPED_SPECIFIC_TAGS`

这通常意味着 preview 后 metadata 变化，或者其他操作改变了映射状态。

用响应中的缺失 SpecificTag 定位对应行，并重新执行 exact/same-origin 查询。
不要直接重试 commit。

## 页面恢复

第一版不保存服务端草稿。刷新页面时重新 preview 并精确查询全部标签。

因为 GenericTag 和 SpecificTag 映射是独立项目资源，已经成功写入的操作会被重新
识别，不需要在浏览器中恢复。

可以使用 `sessionStorage` 记住以下纯界面状态：

- 当前选中的标签 index。
- 左侧筛选条件。
- metadata 折叠状态。

不得把未提交的映射选择当成可靠草稿写入 `localStorage`。

## 安全与输出

- 所有名称和 metadata 以 `textContent` 渲染。
- 不将来源 metadata 拼接进 `innerHTML`。
- 外部 URL 必须验证协议，只允许预期的 `http`/`https` 或站内相对路径。
- 错误详情默认折叠，避免将服务端堆栈直接展示给普通用户。
- 客户端校验只改善体验，所有身份、枚举和唯一性约束仍由服务端验证。
