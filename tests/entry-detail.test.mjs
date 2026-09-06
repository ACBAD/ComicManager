import test from "node:test";
import assert from "node:assert/strict";
import {
  readComic,
  readEntryState,
  readEntryCompletion,
  compareLibraries,
  documentSummary,
} from "../src/pending-comics.js";

const comic = {
  id: 7,
  title: "本地旧标题",
  authors: ["作者"],
  comic_tags: [],
  updated_at: "2026-09-06T00:00:00Z",
};
const document = {
  document_id: 7,
  title: "来源新标题",
  source: "hitomi",
  status: "archived",
  source_meta: { title: "来源新标题" },
  updated_at: "2026-09-05T00:00:00Z",
};
const response = (data, status = 200) =>
  new Response(JSON.stringify(data), { status });
const failure = (code, status) =>
  response({ error: { code, message: code } }, status);

test("单本读取只请求当前 ID，直接保留原始漫画和持久化时间", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push(url);
    assert.equal(options.method, "GET");
    assert.equal(options.body, undefined);
    assert.equal(options.cache, "no-store");
    return response(comic);
  });
  assert.deepEqual(await readComic(7), comic);
  assert.deepEqual(calls, ["/api/comics/7"]);
});

test("只有明确的 404 COMIC_NOT_FOUND 才表示未入库，鉴权和其他失败必须抛出", async (t) => {
  t.mock.method(globalThis, "fetch", async () =>
    failure("COMIC_NOT_FOUND", 404),
  );
  assert.equal(await readComic(7), null);
  for (const [code, status] of [
    ["AUTHENTICATION_REQUIRED", 401],
    ["FORBIDDEN", 403],
    ["HTTP_404", 404],
    ["SOURCE_DOCUMENT_NOT_FOUND", 404],
    ["COMIC_NOT_FOUND", 500],
    ["SERVER_ERROR", 503],
  ]) {
    t.mock.method(globalThis, "fetch", async () => failure(code, status));
    await assert.rejects(
      readComic(7),
      (error) => error.code === code && error.status === status,
    );
  }
  t.mock.method(globalThis, "fetch", async () => {
    throw new TypeError("offline");
  });
  await assert.rejects(readComic(7), { code: "NETWORK_ERROR" });
});

test("错误 ID、空对象或列表不能作为当前漫画", async (t) => {
  for (const value of [null, {}, [], [comic], { ...comic, id: 8 }]) {
    t.mock.method(globalThis, "fetch", async () => response(value));
    await assert.rejects(readComic(7), { code: "INVALID_RESPONSE" });
  }
});

test("单本确认的缺失记录不会再显示尚未核对，也不计入 CM 已读取数量", () => {
  const documents = new Map([
    [7, documentSummary(document)],
    [8, { ...documentSummary(document), document_id: 8 }],
  ]);
  const comics = new Map([
    [100, { ...comic, id: 100 }],
    [7, null],
  ]);
  const result = compareLibraries(documents, comics, {
    full: false,
    cmMinId: 100,
  });
  assert.deepEqual(
    result.pending.map((row) => [row.id, row.reason]),
    [
      [7, "missing"],
      [8, "unchecked"],
    ],
  );
  assert.equal(result.cmTotal, 1);
  assert.deepEqual(
    compareLibraries(new Map(), new Map([[7, null]])).pending,
    [],
  );
});

test("重查当前部允许未入库；提交后的确认必须读到已持久化记录", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(url);
    return url.startsWith("/api/")
      ? failure("COMIC_NOT_FOUND", 404)
      : response(document);
  });
  assert.deepEqual(await readEntryState("https://dmb.example", 7), {
    comic: null,
    document: documentSummary(document),
  });
  await assert.rejects(readEntryCompletion("https://dmb.example", 7), {
    code: "ENTRY_NOT_CONFIRMED",
  });
  assert.deepEqual(
    calls,
    Array(2)
      .fill(["/api/comics/7", "https://dmb.example/v1/documents/7"])
      .flat(),
  );
});

test("确认时来源 ID 不匹配或读取失败，不以缓存来源判断完成", async (t) => {
  t.mock.method(globalThis, "fetch", async (url) =>
    response(url.startsWith("/api/") ? comic : { ...document, document_id: 8 }),
  );
  await assert.rejects(readEntryCompletion("https://dmb.example", 7), {
    code: "INVALID_RESPONSE",
  });
  t.mock.method(globalThis, "fetch", async (url) =>
    url.startsWith("/api/") ? response(comic) : failure("SERVER_ERROR", 503),
  );
  await assert.rejects(readEntryCompletion("https://dmb.example", 7), {
    code: "SERVER_ERROR",
  });
});

test("离开页面取消当前部的两个读取请求，迟到的响应不能更新结果", async (t) => {
  const controller = new AbortController();
  const requests = [];
  t.mock.method(
    globalThis,
    "fetch",
    (url, options) =>
      new Promise((resolve) => {
        requests.push({ url, signal: options.signal, resolve });
      }),
  );
  const pending = readEntryState("https://dmb.example", 7, {
    signal: controller.signal,
  });
  assert.equal(requests.length, 2);
  controller.abort();
  for (const request of requests) {
    assert.equal(request.signal.aborted, true);
    request.resolve(
      response(request.url.startsWith("/api/") ? comic : document),
    );
  }
  await assert.rejects(pending, { name: "AbortError" });
});
