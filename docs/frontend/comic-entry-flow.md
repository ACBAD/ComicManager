# 漫画录入流程

## 总体状态机

```mermaid
flowchart TD
    A["打开漫画录入页"] --> B["GET comic preview"]
    B --> C{"预览成功？"}
    C -- "漫画已存在" --> D["查看已有漫画或返回"]
    C -- "metadata 无效" --> E["阻断并显示错误"]
    C -- "成功" --> F["并发精确查询全部 SpecificTag"]
    F --> G{"全部已有映射？"}
    G -- "是" --> N["最终复核"]
    G -- "否" --> H["进入 Tag 处理工作台"]
    H --> I["选择一个未映射 SpecificTag"]
    I --> J["查询 same_origin 候选"]
    J --> K{"决定 GenericTag"}
    K --> L["创建或复用 GenericTag"]
    L --> M["POST SpecificTag 建立映射"]
    M --> G
    N --> O["POST comic commit"]
    O --> P{"提交结果"}
    P -- "201" --> Q["录入成功"]
    P -- "缺失映射" --> H
    P -- "source 变化" --> B
```

## 1. 进入页面

推荐前端页面路由：

```text
/comics/{comic_id}/entry
```

页面加载后并行执行：

1. `GET /api/tags/groups`
2. `GET /api/comics/{comic_id}/preview`

TagGroup 可以在浏览器会话内缓存；preview 不缓存。

加载期间显示漫画级骨架屏，不先渲染空表单，避免用户误以为漫画没有标签。

## 2. 获取精确映射状态

preview 返回 SpecificTag 后，对每个标签调用：

```http
POST /api/tags/specific/query
{"match": "exact", "specific_tag": {...}}
```

请求应采用有限并发，例如同时 6 个，避免拥有大量标签的漫画瞬间制造过多
SQLite 查询。

每个标签进入以下状态之一：

- `resolved`：精确查询返回一条 SpecificTagView。
- `unresolved`：没有精确记录。
- `error`：网络错误或服务端验证错误。

数据库唯一约束保证精确查询最多得到一条。如果服务端返回多条，应视为数据损坏，
不得由前端自行选择。

## 3. 处理未映射标签

用户选中一个 `unresolved` 标签后，前端执行：

```http
POST /api/tags/specific/query
{"match": "same_origin", "site": "...", "origin_name": "..."}
```

候选结果按 `generic_tag.id` 合并。

### 3.1 有一个 GenericTag 候选

将其显示为“推荐映射”，默认选中但不自动写入。用户点击“采用并处理下一个”后，
才调用 `POST /api/tags/specific`。

这保留 CLI 单候选自动选择的效率，同时让 Web 用户在最终写入前看见决定。

### 3.2 有多个 GenericTag 候选

显示候选目标列表。每个候选下展示促成该候选的 SpecificTag 证据：

- 原始 group
- tag sex
- URL
- site

用户选择的是 GenericTag，不是某条证据 SpecificTag。

### 3.3 没有候选

显示两个互斥操作：

1. 搜索并复用已有 GenericTag。
2. 创建新的 GenericTag。

搜索必须限制在当前选择的 TagGroup 内。

新标签名称默认填入 `origin_name`，但允许编辑。

### 3.4 推断 TagGroup

preview 中的 `inferred_group` 非空时，组选择框预填该值，但允许用户修改。

`inferred_group` 为空时必须人工选择。不得默认选择 `tag`。

### 3.5 Group 特殊流程

当选择或推断结果为 `group`：

1. GenericTag 名称默认且优先采用 `origin_name`。
2. 先精确查询 `tag_group=group + name=origin_name`。
3. 已存在则推荐复用。
4. 不存在则推荐创建。

该规则只是界面快捷行为，最终仍然通过通用 GenericTag 和 SpecificTag API 完成。

### 3.6 male/female 变体

当相同 `site + origin_name` 的 male/female 变体指向同一个 GenericTag 时，页面
只显示一个候选目标，同时展开显示两条来源证据。

可以提供：

> 将相同 origin_name 的当前待处理变体映射到同一 GenericTag

该操作逐条创建 SpecificTag 映射，不合并 SpecificTag，也不删除 metadata。

## 4. 建立映射

复用已有 GenericTag：

```http
POST /api/tags/specific
{
  "specific_tag": {...},
  "generic_tag_id": 17
}
```

创建新 GenericTag：

1. `POST /api/tags/generic`
2. 取得返回的 GenericTag ID。
3. `POST /api/tags/specific`

若创建 GenericTag 时收到 `GENERIC_TAG_EXISTS`，使用响应中的已有标签继续第二步，
不要求用户重新操作。

映射成功后：

- 将该标签状态改为 `resolved`。
- 保留服务端返回的 SpecificTag ID 和 GenericTag。
- 自动选中下一个待处理标签。
- 更新页面总进度。

## 5. 最终复核

只有满足以下条件时才启用“录入漫画”按钮：

- preview 加载成功。
- 所有 SpecificTag 精确映射完成。
- 没有正在进行的 Tag 写请求。
- 没有处于 `error` 状态的标签。

复核区显示：

- 漫画 ID、标题和作者。
- 来源站点和来源 ID。
- SpecificTag 总数。
- 按 GenericTag group 汇总的最终标签。
- 本次会话新建的 GenericTag 和 SpecificTag 数量。

## 6. Comic commit

```http
POST /api/comics/{comic_id}/commit
{"source_revision": "..."}
```

前端不发送 Comic 内容，也不发送映射列表。服务端重新读取并验证所有数据。

响应处理：

- `201`：显示成功页。
- `COMIC_ALREADY_EXISTS`：显示“查看已有漫画”。
- `UNMAPPED_SPECIFIC_TAGS`：用响应中的缺失列表刷新状态，回到工作台。
- `SOURCE_META_CHANGED`：丢弃当前 preview，完整重新加载。
- 其他错误：保留当前页面状态，显示可重试错误。

## 7. 离开页面

第一版不实现服务端草稿。由于 Tag 写操作是即时保存的，已经建立的映射不会丢失。

如果仍有尚未写入的选择或正在进行的请求，关闭或跳转页面前使用
`beforeunload` 提示。仅仅存在未映射标签时不弹提示，因为这些状态尚未产生修改。

