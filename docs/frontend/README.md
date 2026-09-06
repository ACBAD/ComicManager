# ComicManager 前端设计总览

本文档记录 ComicManager 新版 Web 前端的既定设计。目标是在后续上下文丢失、
更换实现者或继续重构时，仍能恢复当前的架构边界和交互意图。

最后更新：2026-09-06。

## 当前实现与运行

- 首页漫画库：`/exploror#/`，展示封面、标题、作者和标签，支持组合检索与分页。
- 录入入口：`/exploror#/entry`，支持输入 DMB 文档 ID 和浏览最近归档。
- 录入工作台：`/exploror#/entry/{comic_id}`。
- 阅读页：`/exploror#/read/{comic_id}`，读取 DMB 页面，支持翻页、页码跳转和原始大小显示。
- 未完成漫画：`/exploror#/pending`，全量扫描 DMB 和 CM，支持搜索、原因与状态筛选及分页。
- 通用标签管理：`/exploror#/tags`，支持分类搜索、新建标签、查看来源映射及分页。
- 页面沿用现有 `/exploror` 和 `/src/{filename}` 路由，未增加后端接口。
- 使用原生 JavaScript 模块与本地 Bootstrap 5.3.8 资源，无前端构建步骤。
- 默认 DMB 地址为 `https://dmb.khadas.hayaseyuuka.date:8880`，浏览器只以 `viewer`
  读取归档。连接设置只改变浏览器的 DMB 地址；应与后端 `DMB_URL` 保持一致。
- 连接设置提供「图片线路」：默认「代理」使用签发原地址；「8880 直连」将已知存储入口
  `https://dmb-oss.hayaseyuuka.date` 替换为 `https://dmb-oss.khadas.hayaseyuuka.date:8880`，
  完整保留路径与签名参数。选择保存在浏览器，封面和阅读页共用，不影响归档 API 地址。
- 本地联调使用 `http://localhost:8000`。该 Origin 在当前 DMB CORS 白名单中；
  `http://127.0.0.1:8000` 与其他端口是不同的 Origin。

临时库启动示例（在项目根目录运行）：

```sh
comic_test_dir=$(mktemp -d)
export COMIC_DB_PATH="$comic_test_dir/comics.db"
export DMB_URL='https://dmb.khadas.hayaseyuuka.date:8880'
.venv/bin/python - <<'PY'
import os, sqlite3
from contextlib import closing
from pathlib import Path
with closing(sqlite3.connect(os.environ['COMIC_DB_PATH'])) as conn:
    conn.executescript(Path('comic.sql').read_text())
PY
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8000
```

前端回归测试：`node --test tests/*.test.mjs`。不要直接执行根目录旧的
`test_comics.py` / `test_tags.py` 做自动测试，它们包含对真实数据库的录入操作。

Bootstrap 文件保留上游 MIT 许可证头，来自
[官方 5.3 下载说明](https://getbootstrap.com/docs/5.3/getting-started/download/)，下载时已校验官方 SHA-384。

## 阅读顺序

1. [API 对接约定](api-contract.md)
2. [漫画录入流程](comic-entry-flow.md)
3. [页面与交互规格](ui-spec.md)
4. [前端状态与异常处理](frontend-state.md)

## 项目边界

Tag 是整个 ComicManager 的一级资源，不是漫画录入流程的内部数据。

API 分为两个资源域：

- `/api/tags` 管理 TagGroup、GenericTag、SpecificTag 及它们的映射关系。
- `/api/comics` 负责已入库漫画的分页读取、组合检索、预览和提交。

不建立 `/api/comic-imports` 这一类只服务于归一化页面的专用资源。漫画录入页面
只是 `/api/tags` 和 `/api/comics` 的一个客户端。

后端直接返回现有 GenericTag、SpecificTag、Comic 模型，标签查询接口返回 ID 数组，
漫画查询接口返回原始 Comic 数组。
前端按需读取详情、映射关系及 DMB 来源信息，自行组织候选和汇总，不要求后端
为页面增加展示模型或拼装关联数据。具体返回结构以 API 对接约定为准。

## 已确定的核心规则

1. `SpecificTag` 的身份由 `site + origin_name + canonical meta_json` 决定。
2. 一个 `SpecificTag` 必须且只能映射到一个 `GenericTag`。
3. 多个不同 metadata 的 `SpecificTag` 可以映射到同一个 `GenericTag`。
   Hitomi 的 male/female 同名 tag 就属于这种情况。
4. `GenericTag` 是不同来源标签的最大公约数；需要细粒度信息时直接查询
   `SpecificTag`。
5. Hitomi 原始 group 保留为字符串。无法推断 `TagGroup` 时必须人工选择，
   不允许自动 fallback 到 `tag`。
6. `GET /api/comics/{comic_id}/preview` 负责读取归档 metadata，并由服务端
   `SiteHandler` 提取 Comic 和 SpecificTag。
7. 前端通过通用 Tag API 查询和补齐映射。
8. `POST /api/comics/{comic_id}/commit` 不接收映射决定。它重新读取来源数据，
   并在所有 SpecificTag 已经具有唯一映射时才录入漫画。
9. Comic commit 必须是单一数据库事务；失败时不得留下部分 Comic 数据。

## 未完成漫画

- 使用 `GET /api/comics?limit=100&offset=…` 读取全部 CM 记录，并通过响应头总数确认完整性。
- DMB 以 `mode=all` 分页读取活动记录，再显式查询 `deleted` / `purged`，不遗漏其他状态。
- 按 DMB `document_id` 与 CM `id` 对应。只有 CM 存在，且其 `updated_at` 严格更晚时才完成；
  时间相同、时间缺失或无法识别均保留在列表中。解析时统一时区并保留纳秒精度。
- CM 中单独存在而 DMB 无对应记录的漫画也列出；已删除、已清理、缺少来源数据以及当前后端
  不支持的来源会显示原因，不提供录入操作。
- 每页请求最多 100 条，页面只缓存列表所需字段。完整扫描成功后才显示对照结果；
  请求失败或取消时可重新扫描，离开页面会取消尚未完成的扫描。
- 页面展示扫描时间，并支持手动重新扫描。各分页请求不共享数据库快照，外部变更后需重新扫描。
- 从此列表进入工作台时保留返回入口与筛选条件。已有 CM 漫画在复核页明确提示替换范围，
  用户点击“确认更新漫画”后调用现有 `commit?allow_override=true`；未入库漫画按原流程提交。
- 返回列表时重新读取 CM 的持久化更新时间，再判断是否完成，不使用提交响应中的空时间或客户端时间。

## 批量自动录入

- 在“未完成漫画”页点击“自动录入”，处理当前筛选范围内所有未入库漫画，涵盖全部分页。
  录入首页提供入口；单部录入工作台继续手动处理，不在打开页面时自动写入。
- 开始前刷新 CM，排除已有记录，再固定本批队列，按漫画逐部处理。
  先取得 preview，再查完全部来源标签的精确映射。
- 全部标签已映射则直接 commit；仅有 group 类标签未映射时，按 `origin_name` 创建或复用
  同组同名 GenericTag，建立并确认映射后 commit。分类依据原始来源字段，保留完整 metadata。
- 只要存在其他未映射标签，整部跳过，不提前创建其中的 group。查询错误、冲突及最新来源
  缺失映射会记录原因并继续下一部；认证或权限不足时停止整批。不会使用 `allow_override` 覆盖已有漫画。
- 单部与批量 commit 均无需请求体，服务端使用提交时从 DMB 读取的最新数据，不依赖预览版本。
- 页面显示总数、当前漫画、录入/跳过/失败计数及逐部结果。停止按钮完成当前漫画后生效；
  运行期间锁定筛选、重新扫描、服务设置和其他写操作。结束后刷新 CM，成功项从未入库范围移除。
  部分 group 已保存后若后续步骤失败，已有映射保留，下次运行会重新精确查询并复用。

## 漫画库与检索

- 展示、检索和阅读是主流程，录入与未完成列表为辅助入口。
- 通过 `POST /api/comics/query` 按标题、作者及通用标签 ID 组合检索，使用响应头
  `X-Total-Count` 分页。默认每页 20 部，可切换 50 / 100 部；顶部和底部均可输入页码跳转。
- 标题默认包含匹配，作者默认精确匹配；均可选择包含、精确、前缀。匹配区分大小写。
- 标签使用单个多选输入框：输入文字后跨分类提示包含该文字的 GenericTag，点选后变成
  框内可移除的标签块，并可继续输入。相同名称显示分类以区分；支持方向键、Enter、Escape
  及空输入时 Backspace 删除最后一个标签。选好后点击“检索”应用条件。
- 提示查询每个分类最多读取 12 项，超出时提示继续输入缩小范围。输入防抖 280ms，
  新输入、失焦和离开页面时取消旧查询，中文输入法组合期间不提交中间文字。
- 多标签支持全部满足 / 任一满足；标签、作者和标题三类条件之间取交集。
- 点击漫画的作者或标签可立即进一步筛选。封面和标题进入阅读；“整理”为次要操作。
- 漫画保留完整原始字段。浏览器对当前页的来源标签去重，分别查询精确身份、GenericTag
  关系及 ID，按通用标签去重展示；不要求后端提供 View 或预先拼装关联。
- DMB 元数据和图片单独读取；某个来源或标签读取失败不会阻止其余漫画展示。
- `title`、`author`、`tags`、匹配方式、`page`、`size` 保存于 hash 查询参数中，
  刷新及浏览器前进/后退均会恢复；阅读和整理链接携带返回查询，返回时重新读取漫画库。
- 从漫画库进入整理时识别已有记录，在复核页明确提示更新，用户确认后才覆盖。

## 阅读

- 沿用 `/exploror` 的 hash 路由，不增加页面后端路由。DMB 文档提供标题和 pages，
  图片先读取 `/v1/documents/{id}/pages/{index}?url=1&token=viewer` 返回的纯文本签发 URL，
  再按图片线路设置加载；不依赖 Content-Type，也不尝试从浏览器的 302 响应读取 Location。
- 直连替换依赖当前 Nginx 网关将 Host 还原为原始签发域名；不适用于任意 S3 服务。
  其他存储域名原样使用，不做通用的签名域名替换。签发 URL 只用于当次加载，不写入本地存储。
- 仅切换图片线路时保留当前页码、显示尺寸、检索输入及录入草稿，清空旧线路缓存并重新预加载。
- 按实际 `index` 排序，展示序号从 1 开始，不假定来源页面连续或从 0 开始。
- 支持左右按钮、方向键、页码跳转；适应窗口模式下支持水平滑动翻页，原始大小模式保留滚动。
- 页码写入当前阅读链接，刷新后恢复；到达首末页时禁用对应翻页按钮。
- 打开后从当前页开始逐张预加载，每张完成后读取下一张，到末尾后补齐之前的页面，
  直到整部完成或退出阅读。跳到未缓存的页面时优先加载目标页，随后继续被中断的预读。
- 已下载的图片以 Blob 和本地对象 URL 保留到本次阅读结束，翻回时不重新签发或下载。
  仅显示当前页时解码，不同时解码整部；状态栏显示已缓存页数及预加载进度。
  图片存储需要允许页面来源通过 CORS 读取图片内容。
- 单页失败或超时后继续预读后续页面，状态栏显示未成功页数；打开失败页会重新尝试，
  当前页仍失败时提供重试。空页面及删除来源有独立提示。
- 阅读离开后取消队列、请求和计时器，并释放图片缓存。外部来源只读，不修改 DMB 数据。

## 领域词汇

- **GenericTag**：跨站点使用的通用标签，例如 `tag / glasses`。
- **SpecificTag**：携带站点原始 metadata 的来源标签。
- **精确映射**：数据库中存在完整 SpecificTag 身份对应的记录。
- **相似标签**：`site + origin_name` 相同，但 metadata 不同的 SpecificTag。
- **候选目标**：相似 SpecificTag 当前映射到的 GenericTag。
- **组选择**：用户根据原始 SpecificTag 信息选择的 GenericTag 分类。
- **待处理标签**：尚不存在精确映射的 SpecificTag。

## 相关源码

- [`tags.py`](../../tags.py)：Tag 领域模型和数据库操作。
- [`comics.py`](../../comics.py)：Comic 模型、预览构造与录入逻辑。
- [`handlers.py`](../../handlers.py)：站点 metadata 解析。
- [`comic.sql`](../../comic.sql)：Tag 和 Comic 数据库约束。
- [`test_comics.py`](../../test_comics.py)：当前 CLI 录入流程的行为基线。
