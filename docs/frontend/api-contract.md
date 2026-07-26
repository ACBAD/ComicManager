# 前端 API 对接约定

本文不是 OpenAPI 的替代品，而是记录前端依赖的语义。服务端实现完成后，应以
实际 OpenAPI schema 补全字段类型，但不得悄悄改变这里记录的资源边界。

## API 树

```text
/api/tags
├── GET  /groups
├── /specific
│   ├── POST /query
│   ├── POST /
│   ├── GET  /{specific_tag_id}
│   └── GET  /{specific_tag_id}/generic
└── /generic
    ├── POST /query
    ├── POST /
    ├── GET  /{generic_tag_id}
    └── GET  /{generic_tag_id}/specifics

/api/comics
├── GET  /{comic_id}/preview
└── POST /{comic_id}/commit
```

## 公共 DTO

### GenericTagView

API 返回的 GenericTag 必须包含数据库 ID，不能直接复用当前不含 ID 的领域模型。

```json
{
  "id": 17,
  "tag_group": "tag",
  "name": "glasses"
}
```

### SpecificTagPayload

SpecificTag 使用与 Pydantic 判别联合一致的扁平结构。客户端不得发送
`meta_json` 字符串，canonical JSON 只能由服务端生成。

```json
{
  "site": "hitomi",
  "origin_name": "glasses",
  "group": "tags",
  "tag_sex": "female",
  "url": "/tag/glasses-female-1.html"
}
```

不同站点可以有不同特有字段，但 `site` 和 `origin_name` 始终存在。

### SpecificTagView

```json
{
  "id": 41,
  "specific_tag": {
    "site": "hitomi",
    "origin_name": "glasses",
    "group": "tags",
    "tag_sex": "female",
    "url": "/tag/glasses-female-1.html"
  },
  "generic_tag": {
    "id": 17,
    "tag_group": "tag",
    "name": "glasses"
  }
}
```

## TagGroup

```http
GET /api/tags/groups
```

响应：

```json
[
  "tag",
  "property",
  "character",
  "parody",
  "expo",
  "group",
  "language"
]
```

前端选择框以该响应为权威来源，不另外硬编码可用枚举。

## GenericTag

### 查询

```http
POST /api/tags/generic/query
Content-Type: application/json
```

```json
{
  "tag_group": "tag",
  "name": "glass",
  "name_match": "contains",
  "limit": 20,
  "offset": 0
}
```

`name_match` 第一版支持：

- `exact`
- `prefix`
- `contains`

响应：

```json
{
  "items": [
    {
      "id": 17,
      "tag_group": "tag",
      "name": "glasses"
    }
  ],
  "total": 1
}
```

### 创建

```http
POST /api/tags/generic
```

```json
{
  "tag_group": "tag",
  "name": "glasses"
}
```

成功返回 `201 Created` 和 `GenericTagView`。同组同名已存在时返回
`409 GENERIC_TAG_EXISTS`，并在错误响应中携带已有 GenericTag，前端可直接改为复用。

### 获取单个标签

```http
GET /api/tags/generic/{generic_tag_id}
```

### 获取来源标签

```http
GET /api/tags/generic/{generic_tag_id}/specifics
```

该接口必须分页。它用于检查一个 GenericTag 当前包含的站点变体，不参与
Comic commit。

## SpecificTag

### 精确查询

```http
POST /api/tags/specific/query
```

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

服务端必须先将输入解析成正确的 SpecificTag 子类，再使用 canonical metadata
查询。前端不能参与 JSON identity 的生成。

### 查询相似标签

```http
POST /api/tags/specific/query
```

```json
{
  "match": "same_origin",
  "site": "hitomi",
  "origin_name": "glasses",
  "limit": 50,
  "offset": 0
}
```

`same_origin` 只匹配 `site + origin_name`，不比较 metadata。响应中的每条
SpecificTag 都应携带其 GenericTag。

前端展示候选时必须按 `generic_tag.id` 分组。多个 SpecificTag 指向同一个
GenericTag 时，它们是同一个候选目标，只是有多条证据。

### 创建并映射

```http
POST /api/tags/specific
```

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

成功返回 `201 Created` 和 `SpecificTagView`。

SpecificTag 在数据库中不能处于“尚未映射”的状态，因此不存在只创建
SpecificTag、不指定 GenericTag 的写法。

若相同身份已经映射：

- 指向同一 GenericTag 时，服务端可以返回幂等成功。
- 指向另一 GenericTag 时，返回 `409 SPECIFIC_TAG_MAPPING_CONFLICT`。

第一版不提供修改映射接口。将来如需纠错，应单独增加受权限控制的
`PUT /api/tags/specific/{id}/generic`。

### 关系查询

```http
GET /api/tags/specific/{specific_tag_id}
GET /api/tags/specific/{specific_tag_id}/generic
```

## Comic preview

```http
GET /api/comics/{comic_id}/preview
```

`comic_id` 是归档数据库 `documents.id`。服务端通过该记录的 `source` 字段
选择 SiteHandler，不需要客户端在 URL 中重复指定站点。

建议响应：

```json
{
  "source": {
    "site": "hitomi",
    "source_document_id": "123456",
    "meta": {}
  },
  "comic": {
    "id": 12345,
    "title": "Example",
    "authors": ["artist"],
    "series_name": null,
    "volume_number": null
  },
  "specific_tags": [
    {
      "specific_tag": {
        "site": "hitomi",
        "origin_name": "glasses",
        "group": "tags",
        "tag_sex": "female",
        "url": "/tag/glasses-female-1.html"
      },
      "inferred_group": null
    }
  ],
  "source_revision": "sha256:..."
}
```

`source.meta` 是原始 metadata；`comic` 和 `specific_tags` 是服务端解析结果。
前端不得重新实现 `SiteHandler.extract_tags()`。

`inferred_group` 是服务端调用 `SpecificTag.inference_group()` 得到的只读提示。
它不是已完成的映射，也不写入 SpecificTag metadata。

## Comic commit

```http
POST /api/comics/{comic_id}/commit
```

```json
{
  "source_revision": "sha256:..."
}
```

该请求不接收映射决策。服务端必须重新读取归档 metadata、重新提取全部
SpecificTag，并确认每个完整身份都已经存在唯一映射。

成功返回 `201 Created`：

```json
{
  "comic": {
    "id": 12345,
    "title": "Example",
    "authors": ["artist"]
  },
  "specific_tag_count": 20
}
```

若存在未映射标签，返回 `409 UNMAPPED_SPECIFIC_TAGS`，并携带当前缺失的
SpecificTag 列表。前端应重新查询这些标签，而不是盲目重复 commit。

## 统一错误格式

```json
{
  "error": {
    "code": "SPECIFIC_TAG_MAPPING_CONFLICT",
    "message": "该来源标签已经映射到其他 GenericTag",
    "details": {}
  }
}
```

前端逻辑依赖稳定的 `error.code`，不解析自然语言 `message`。

建议错误码：

| HTTP | code | 前端行为 |
|---|---|---|
| 404 | `SOURCE_DOCUMENT_NOT_FOUND` | 显示归档记录不存在 |
| 404 | `GENERIC_TAG_NOT_FOUND` | 刷新候选并要求重选 |
| 409 | `GENERIC_TAG_EXISTS` | 使用响应中的已有标签 |
| 409 | `SPECIFIC_TAG_MAPPING_CONFLICT` | 刷新该 SpecificTag |
| 409 | `COMIC_ALREADY_EXISTS` | 提供查看已有漫画入口 |
| 409 | `SOURCE_META_CHANGED` | 重新加载 preview |
| 409 | `UNMAPPED_SPECIFIC_TAGS` | 返回标签处理阶段 |
| 422 | `INVALID_SPECIFIC_TAG` | 展示 metadata 校验详情 |
| 422 | `META_SCHEMA_VIOLATION` | 阻断并要求维护者处理 |

