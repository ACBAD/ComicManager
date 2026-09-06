# 前端状态与异常处理

## 漫画库与阅读状态

- `comic-library.js` 负责查询参数与 URL 往返、读取原始 Comic、解析标签关系和 DMB 页索引。
- `library-page.js` 管理已应用查询、输入框草稿和标签候选。候选选择只修改草稿，
  提交后写入 hash 并重新查询；URL 是已应用条件和分页的恢复依据。
- 标签候选跨分类查询与详情读取均采用有限并发。当前页来源标签先按完整身份去重，
  对应的 GenericTag ID 查询也去重；每次刷新重新读取，避免缓存已变化的关系。
- 漫画原始字段先展示，封面和通用标签异步补充。外部图片或部分标签不可用时，
  保留漫画与其他已经取得的字段，并提供局部重试。
- `reader-image-cache.js` 按 DMB 实际页面索引维护整部预读队列，同一时间只加载一页。
  从当前页读到末尾，再补齐前面的页面；跳页优先处理目标页，完成后继续未读队列。
  同页请求复用 Promise，成功后保留压缩图片 Blob 对应的对象 URL，回翻直接使用缓存。
  单页 30 秒超时或读取失败后继续队列，失败页再次显示时重新请求，不计为缓存成功。
- `comic-reader.js` 等待当前页 `decode()` 成功后替换旧图片，提供当前页重试与缓存进度。
  翻页递增显示版本，旧响应不能覆盖新页面；退出、换漫画或切换图片线路时取消队列，
  释放全部对象 URL，迟到的结果同样释放。
- 图片 URL 通过 DMB 的 `?url=1` 纯文本接口获取，图片线路保存在
  `localStorage["comicmanager.imageRoute"]`（`proxy` / `direct`，默认 `proxy`）。
  切换线路取消旧签发和图片请求；阅读页从当前页重新预读整部，漫画库只重载封面，
  不重建检索表单。
  签发请求禁止跟随重定向，返回内容必须是无嵌入凭据的 HTTP / HTTPS URL。
- 页面路由统一取消上一个页面的请求。检索结果分页超出末页时替换为有效末页，
  不新增多余的浏览器历史记录。

## 页面状态

批量录入由 `batch-entry.js` 执行，`manager.js` 管理独立的队列进度和结果，不复用单部录入
工作台的选中项或候选状态。点击按钮时重新读取 CM，并从当前筛选结果的全部分页中排除已入库
记录。漫画串行处理，单部的精确标签查询最多 6 路，全部查询结束后才决定是否写入。

运行期间用 `pendingWrites` 锁定其他写操作和路由跳转。停止请求仅在漫画之间检查，
不取消可能已经落库的写请求。一次提交失败不会阻断后续漫画；401/403 停止整批。
结束后重新读取 CM 的持久化时间再更新列表；刷新失败时保留逐部结果并提示重新扫描。
结果仅保留在当前页面会话中，刷新页面后可重新扫描并运行，已入库记录不会再次进入队列。

原生 JavaScript 第一版建议维护一个单一页面状态对象：

```js
const state = {
  phase: 'loading',
  comicId: null,
  groups: [],
  preview: null,
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

### 提交时的来源数据

commit 不需要预览版本，始终从 DMB 重新读取最新 metadata。标题、作者和已映射标签的变化
直接使用最新内容；如新增标签尚未映射，则按 `UNMAPPED_SPECIFIC_TAGS` 处理。
已写入数据库的 Tag 映射不会因漫画提交失败回滚，重新精确查询时继续复用。

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
