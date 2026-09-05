# API 对接约定

2026-09-05：接口直接返回现有 GenericTag、SpecificTag、Comic 领域模型。
不增加展示模型，不在详情中嵌入其他资源，也不为录入页面预先组合候选、推断或汇总。
ID 通过查询接口取得；前端需要详情或关系时，调用对应接口。

读取接口要求登录。创建标签要求 `tag.create`，录入漫画要求 `document.create`；
管理员直接放行。每个需要访问数据库的请求使用独立 SQLite 连接，请求结束时关闭；
ComicManager 与其 TagManager 在该请求内共用连接，事务由 Manager 的业务操作管理。
DMB 使用同步 HTTP 客户端，由应用 lifespan 创建、检查健康状态并在关闭时释放。

## 返回规则

| 操作 | 响应体 |
|---|---|
| GenericTag 创建、详情 | 原始 GenericTag |
| SpecificTag 创建、详情 | 原始 SpecificTag |
| 标签查询、通用标签的来源标签查询 | ID 数组 |
| SpecificTag 对应的 GenericTag | 原始 GenericTag |
| Comic 预览、录入成功 | 原始 Comic |

标签查询结果按 ID 升序，响应体例如 `[17, 23]`。无匹配项时返回 `[]`。
分页前的匹配总数放在响应头 `X-Total-Count`，不额外包装响应体。

GenericTag 保持原模型结构，不添加 ID：

```json
{"tag_group": "tag", "name": "glasses"}
```

SpecificTag 保持原模型结构，由 `site` 判别具体类型。例如：

```json
{
  "site": "hitomi",
  "origin_name": "glasses",
  "group": "tags",
  "tag_sex": "female",
  "url": "/tag/glasses-female-1.html"
}
```

不附加 GenericTag、数据库外键或推断组。可选字段按领域模型正常序列化为 null。
SpecificTag 的完整身份仍是 `site + origin_name + canonical metadata`；
canonical JSON 由后端生成，客户端不发送 `meta_json` 字符串。

## TagGroup

`GET /api/tags/groups` 返回 TagGroup 值的数组。

## GenericTag

### 查询 ID

`POST /api/tags/generic/query`

```json
{
  "tag_group": "tag",
  "name": "glass",
  "name_match": "contains",
  "limit": 20,
  "offset": 0
}
```

- `name_match` 支持 exact、prefix、contains，默认 exact。
- 名称匹配区分大小写，% 和 _ 是普通字符；不传 name 时查询该组全部标签。
- limit 默认 20、范围 1–100；offset 默认 0 且不得为负数。
- 返回 ID 数组；前端按需调用详情接口。

### 创建与读取

`POST /api/tags/generic` 接收 GenericTag，成功返回 201 和同一领域模型。
同组同名已存在时返回 409 GENERIC_TAG_EXISTS。需要 ID 时按组和名称精确查询。
名称不得为空或纯空白，不自动裁剪。

`GET /api/tags/generic/{id}` 返回 GenericTag，不存在时返回 404。

`GET /api/tags/generic/{id}/specifics?limit=50&offset=0` 返回关联的 SpecificTag ID
数组。limit 范围 1–100；GenericTag 不存在时返回 404。

## SpecificTag

### 精确查询 ID

`POST /api/tags/specific/query`

```json
{
  "match": "exact",
  "specific_tag": {
    "site": "hitomi",
    "origin_name": "glasses",
    "group": "tags",
    "tag_sex": "female",
    "url": "/tag/glasses-female-1.html"
  }
}
```

返回零个或一个 ID。字段顺序、显式 null 与省略可选字段不改变 identity。
查询不会创建标签或 schema 记录。

### 同原名查询 ID

`POST /api/tags/specific/query`

```json
{
  "match": "same_origin",
  "site": "hitomi",
  "origin_name": "glasses",
  "limit": 50,
  "offset": 0
}
```

只按 site 和 origin_name 查询，返回 ID 数组。limit 范围 1–100，offset 不得为负数。
此模式不接收 specific_tag。前端需要候选的 metadata 或映射目标时分别读取详情和关系。

### 创建映射

`POST /api/tags/specific`

```json
{
  "specific_tag": {
    "site": "hitomi",
    "origin_name": "glasses",
    "group": "tags",
    "tag_sex": "female",
    "url": "/tag/glasses-female-1.html"
  },
  "generic_tag_id": 17
}
```

新建成功返回 201 和原始 SpecificTag。相同身份已映射到同一 GenericTag 时返回 200
和原始 SpecificTag；指向另一 GenericTag 时返回 409 SPECIFIC_TAG_MAPPING_CONFLICT。
错误响应不附带拼装后的资源。前端通过精确查询和关系接口读取当前映射。

SpecificTag 必须映射到已有 GenericTag，不提供未映射记录或覆盖映射操作。

### 详情与关系

- `GET /api/tags/specific/{id}`：返回 SpecificTag。
- `GET /api/tags/specific/{id}/generic`：返回对应的 GenericTag。
- 需要该 GenericTag 的 ID 时，使用其 tag_group 和 name 精确查询。

## Comic

### 预览

`GET /api/comics/{comic_id}/preview` 从 DMB 读取来源数据，由现有 SiteHandler
构造 Comic，直接返回该模型，不要求本地已录入，不写入本地数据。

JSON 字段保持 Comic 原定义：id、title、authors、comic_tags、series_name、
volume_number、updated_at。comic_tags 是原始 SpecificTag 数组，不添加映射、
来源摘要、inferred_group 或页面统计。额外来源信息由客户端按需读取 DMB。

响应包含 `Cache-Control: no-store`。保留来源版本校验，版本通过标准 ETag 响应头传递，
例如 `ETag: "sha256:…"`，不混入 Comic 数据。
摘要覆盖 DMB 的 document_id、source、source_document_id、source_meta，
不受 JSON 字段顺序和下载进度影响。

### 录入

`POST /api/comics/{comic_id}/commit?allow_override=false`

```json
{"source_revision": "sha256:..."}
```

source_revision 取自预览的 ETag，去掉 HTTP 引号，格式为 sha256: 加 64 位十六进制摘要。
服务端重新读取来源并校验版本、完整标签身份及映射；不接收客户端提供的 Comic 或映射决定。
成功返回 201 和原始 Comic，不再返回摘要或标签计数。

来源变化返回 409 SOURCE_META_CHANGED；缺失映射返回 409 UNMAPPED_SPECIFIC_TAGS，
其 error.details.specific_tags 为缺失的原始 SpecificTag 数组。
已经录入且未允许覆盖时返回 409 COMIC_ALREADY_EXISTS。

allow_override=true 时，在单一事务中替换漫画及作者、标签关联。任何写入失败均回滚。
重复作者或标签身份只写一份关联；独立保存的标签映射不会随漫画录入失败回滚。

## 错误

领域错误和参数错误保留统一错误格式：

```json
{"error": {"code": "GENERIC_TAG_EXISTS", "message": "同组同名的通用标签已存在", "details": {}}}
```

常用错误码：

| HTTP | code |
|---|---|
| 401 / 403 | AUTHENTICATION_REQUIRED / FORBIDDEN |
| 404 | GENERIC_TAG_NOT_FOUND / SPECIFIC_TAG_NOT_FOUND / SOURCE_DOCUMENT_NOT_FOUND |
| 409 | GENERIC_TAG_EXISTS / SPECIFIC_TAG_MAPPING_CONFLICT / COMIC_ALREADY_EXISTS |
| 409 | SOURCE_META_CHANGED / UNMAPPED_SPECIFIC_TAGS |
| 422 | INVALID_REQUEST / INVALID_SPECIFIC_TAG / INVALID_SOURCE_METADATA / META_SCHEMA_VIOLATION |
| 502 / 504 | SOURCE_SERVICE_ERROR / SOURCE_SERVICE_TIMEOUT |

META_SCHEMA_VIOLATION 的详情包含 specific_tag、db_schema_hash、tag_schema_hash。
参数校验失败的详情包含 errors；资源详情和关系由客户端另行查询。
