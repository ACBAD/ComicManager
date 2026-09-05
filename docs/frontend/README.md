# ComicManager 前端设计总览

本文档记录 ComicManager 新版 Web 前端的既定设计。目标是在后续上下文丢失、
更换实现者或继续重构时，仍能恢复当前的架构边界和交互意图。

最后更新：2026-09-05。

## 当前实现与运行

- 首页：`/exploror#/`，支持输入 DMB 文档 ID 和浏览最近归档。
- 录入工作台：`/exploror#/entry/{comic_id}`。
- 未完成漫画：`/exploror#/pending`，全量扫描 DMB 和 CM，支持搜索、原因与状态筛选及分页。
- 通用标签管理：`/exploror#/tags`，支持分类搜索、新建标签、查看来源映射及分页。
- 页面沿用现有 `/exploror` 和 `/src/{filename}` 路由，未增加后端接口。
- 使用原生 JavaScript 模块与本地 Bootstrap 5.3.8 资源，无前端构建步骤。
- 默认 DMB 地址为 `https://dmb.khadas.hayaseyuuka.date:8880`，浏览器只以 `viewer`
  读取归档。连接设置只改变浏览器的 DMB 地址；应与后端 `DMB_URL` 保持一致。
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
- `/api/comics` 负责已入库漫画的分页读取、预览和提交。

不建立 `/api/comic-imports` 这一类只服务于归一化页面的专用资源。漫画录入页面
只是 `/api/tags` 和 `/api/comics` 的一个客户端。

后端直接返回现有 GenericTag、SpecificTag、Comic 模型，查询接口返回 ID 数组。
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
