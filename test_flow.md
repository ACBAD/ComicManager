# 测试指南：Comic 缓存与下载管理器

本文档旨在提供一个清晰的流程，用于测试 `cache_manager.py` 中实现的 FastAPI 应用的功能，包括异步下载、任务状态查询和缓存管理。

---

## 1. 环境准备

在开始测试之前，请确保您已安装所有必要的依赖项。主要的依赖包括：

- `fastapi`: Web 框架。
- `uvicorn`: ASGI 服务器，用于运行 FastAPI 应用。
- `diskcache`: 核心缓存库。
- `requests` 或 `httpx`: (可选) 用于从命令行发送 HTTP 请求的客户端。
- `pyzipper`: 用于处理加密的 zip 文件。

您可以使用 `pip` 安装它们：
```bash
pip install fastapi uvicorn diskcache requests pyzipper
```

## 2. 启动应用

使用 `uvicorn` 从命令行启动 FastAPI 应用。假设您的应用实例名为 `app`，位于 `cache_manager.py` 文件中。

```bash
# 在项目根目录 D:/CodeLib/ComicManager/ 下运行
uvicorn cache_manager:app --reload --port 8000
```

服务器现在应该在 `http://127.0.0.1:8000` 上运行。

## 3. 测试流程

以下步骤将引导您完成对各个 API 端点的测试。您可以使用 `curl` 工具或者任何图形化的 API 测试工具（如 Postman）来发送请求。

### 第 1 步：发起一个新的下载任务

向 `/download` 端点发送一个 `POST` 请求来启动一个漫画的下载任务。

**请求示例 (使用 curl):**

```bash
# 请求从 Cloudflare R2 下载一个名为 'some_comic.zip' 的文件
curl -X POST "http://127.0.0.1:8000/download" -H "Content-Type: application/json" -d '{ "comic_name": "some_comic.zip", "source": "r2" }'

# 请求从 Lanzou 下载一个文件
curl -X POST "http://127.0.0.1:8000/download" -H "Content-Type: application/json" -d '{ "comic_name": "another_comic.zip", "source": "lanzou" }'
```

**预期响应:**

如果任务被成功接受，您会收到一个 `202 Accepted` 状态码和包含 `task_id` 的 JSON 响应。

```json
{
  "task_id": "some_comic.zip_r2_1678886400",
  "message": "Task accepted."
}
```

记下这个 `task_id`，后续步骤会用到它。

### 第 2 步：查询任务状态

在下载进行期间，您可以查询任务的状态和进度。

**A. 查询所有任务**

向 `/tasks` 端点发送 `GET` 请求。

```bash
curl -X GET "http://127.0.0.1:8000/tasks"
```

**B. 查询特定任务**

使用上一步获得的 `task_id`，向 `/tasks/{task_id}` 端点发送 `GET` 请求。

```bash
curl -X GET "http://127.0.0.1:8000/tasks/some_comic.zip_r2_1678886400"
```

**预期响应:**

您将看到任务的详细信息。在下载过程中，`status` 会从 `queued` 变为 `downloading`，`progress` 会实时更新。下载完成后，`status` 会变为 `completed`。

```json
{
  "task_id": "some_comic.zip_r2_1678886400",
  "comic_name": "some_comic.zip",
  "source": "r2",
  "status": "downloading",
  "progress": 45.78,
  "error_message": null
}
```

### 第 3 步：验证漫画是否已缓存

当任务状态变为 `completed` 后，该漫画文件应该已经被存储在缓存中。

向 `/cache/{comic_name}` 端点发送 `GET` 请求来验证。

**请求示例:**

```bash
curl -X GET "http://127.0.0.1:8000/cache/some_comic.zip"
```

**预期响应:**

如果文件在缓存中，您会收到一个 `200 OK` 响应。

```json
{
  "status": "found_in_cache"
}
```

### 第 4 步：测试缓存未命中和自动下载

请求一个您确定不在缓存中的漫画。

**请求示例:**

```bash
curl -X GET "http://127.0.0.1:8000/cache/a_new_comic.zip"
```

**预期响应:**

应用会返回 `202 Accepted`，并告知一个新的下载任务已经自动启动。响应中会包含新任务的 `task_id`。

```json
{
  "status": "not_in_cache_download_started",
  "task_id": "a_new_comic.zip_r2_1678886500"
}
```

您可以使用这个新的 `task_id` 重复**第 2 步**来监控其下载进度。

### 第 5 步：测试重复任务的冲突

尝试为一个正在下载或已在队列中的漫画再次发起下载请求。

**请求示例:**

```bash
# 假设 'some_comic.zip' 正在下载中
curl -X POST "http://127.0.0.1:8000/download" -H "Content-Type: application/json" -d '{ "comic_name": "some_comic.zip", "source": "r2" }'
```

**预期响应:**

服务器会返回 `409 Conflict` 状态码，告知任务已在进行中。

```json
{
  "detail": "Task for this comic is already in progress."
}
```

---

## 4. 物理验证 (可选)

您可以直接检查 `diskcache` 的物理存储目录，以确认文件是否被正确创建。

1.  **定位缓存目录**: 缓存目录由 `site_utils.archived_comic_path` 变量定义。
2.  **检查文件**: 在该目录中，您会看到 `diskcache` 创建的数据文件。当一个漫画下载完成并存入缓存后，相应的数据会出现在这里。
3.  **观察清理**: 虽然很难精确测试，但 `diskcache` 会在缓存大小接近 10GB 上限时，自动删除最久未被访问的文件。
