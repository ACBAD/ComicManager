import test from "node:test";
import assert from "node:assert/strict";
import {
  readLibrariesUntilAnchor,
  entryQueue,
  entryBlockReason,
  retainPendingDocuments,
  compareLibraries,
  documentSummary,
  readEntryCompletion,
} from "../src/pending-comics.js";

const doc = (id, day = 5, extra = {}) => ({
  document_id: id,
  title: `comic ${id}`,
  source: "hitomi",
  status: "archived",
  source_meta: { title: "metadata" },
  updated_at: `2026-09-0${day}T12:00:00.123456789Z`,
  ...extra,
});
const cm = (id) => ({
  id,
  title: `comic ${id}`,
  updated_at: "2026-09-06T00:00:00Z",
});
const response = (data, total) =>
  new Response(JSON.stringify(data), {
    headers: total === undefined ? {} : { "X-Total-Count": String(total) },
  });
const map = (rows) =>
  new Map(rows.map((row) => [row.document_id, documentSummary(row)]));
const scan = (options) =>
  readLibrariesUntilAnchor("https://dmb.example", options);
function mockPages(t, comics, dmbPage) {
  const cmCalls = [],
    dmbCalls = [];
  const sorted = [...comics].sort((a, b) => b.id - a.id);
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const body = JSON.parse(options.body);
    if (url === "/api/comics/query") {
      cmCalls.push(body);
      assert.equal(body.order, "DESC");
      assert.equal(body.limit, 100);
      return response(
        sorted.slice(body.offset, body.offset + body.limit),
        sorted.length,
      );
    }
    dmbCalls.push(body);
    return response(await dmbPage(body));
  });
  return { cmCalls, dmbCalls };
}

test("首批 CM 和 DMB 各 100 条同时发出，命中 anchor 后不读取剩余 CM", async (t) => {
  let releaseCM, releaseDMB;
  const calls = [];
  t.mock.method(globalThis, "fetch", (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    return new Promise((resolve) => {
      if (url.startsWith("/api")) releaseCM = resolve;
      else releaseDMB = resolve;
    });
  });
  const pending = scan();
  assert.equal(calls.length, 2, "两个请求必须在任何响应返回前发出");
  assert.deepEqual(
    calls.map((call) => call.body),
    [
      { order: "DESC", limit: 100, offset: 0 },
      {
        mode: "all",
        orderby: "updated_at",
        order: "DESC",
        limit: 100,
        offset: 0,
      },
    ],
  );
  releaseCM(
    response(
      Array.from({ length: 100 }, (_, i) => cm(5000 - i)),
      400,
    ),
  );
  releaseDMB(
    response([
      doc(5001),
      doc(4999, 4),
      ...Array.from({ length: 98 }, (_, i) => doc(4998 - i, 3)),
    ]),
  );
  const result = await pending;
  assert.equal(result.anchor.document_id, 4999);
  assert.deepEqual([...result.documents.keys()], [5001, 4999]);
  assert.equal(result.comics.size, 100);
  assert.equal(result.cmTotal, 400);
  assert.equal(result.cmComplete, false);
  assert.equal(result.dmbLoaded, 100);
  assert.equal(calls.length, 2);
});

test("CM 尚未读到的旧 ID 保留待核对，已确认 anchor 后立即停止", async (t) => {
  const { cmCalls, dmbCalls } = mockPages(
    t,
    Array.from({ length: 210 }, (_, i) => cm(i + 1)),
    () => [doc(8), doc(202, 4), doc(200, 3)],
  );
  const result = await scan();
  assert.equal(result.anchor.document_id, 202);
  assert.deepEqual([...result.documents.keys()], [8, 202]);
  assert.deepEqual(
    cmCalls.map((body) => body.offset),
    [0],
  );
  assert.equal(dmbCalls.length, 1);
  const pending = compareLibraries(result.documents, result.comics, {
    full: false,
    cmMinId: result.cmMinId,
  }).pending;
  assert.deepEqual(
    pending.map((row) => [row.id, row.reason]),
    [[8, "unchecked"]],
  );
});

test("下一批 CM 可以匹配上一批 DMB，不会只对比同一页", async (t) => {
  const { cmCalls, dmbCalls } = mockPages(
    t,
    Array.from({ length: 210 }, (_, i) => cm(i + 1)),
    ({ offset }) =>
      offset
        ? [doc(500, 4)]
        : Array.from({ length: 100 }, (_, i) => doc(i + 1)),
  );
  const result = await scan();
  assert.equal(result.anchor.document_id, 11);
  assert.equal(result.cmComplete, false);
  assert.equal(cmCalls.length, 2);
  assert.equal(dmbCalls.length, 2);
  assert.equal(result.documents.size, 100);
  assert.ok(result.comics.has(11));
});

test("CM 同时间或比来源更旧均不能作为 anchor；CM 读完后只继续 DMB 分页", async (t) => {
  const { cmCalls, dmbCalls } = mockPages(
    t,
    [
      { ...cm(1), updated_at: doc(1).updated_at },
      { ...cm(2), updated_at: doc(2, 3).updated_at },
    ],
    ({ offset }) =>
      offset
        ? [doc(101, 4)]
        : Array.from({ length: 100 }, (_, i) => doc(i + 1)),
  );
  const result = await scan();
  assert.equal(result.anchor, null);
  assert.equal(result.documents.size, 101);
  assert.deepEqual(
    dmbCalls.map((body) => body.offset),
    [0, 100],
  );
  assert.equal(cmCalls.length, 1);
});

test("两边都还有未读取页且无 anchor 时，继续每次各取 100 条", async (t) => {
  const { cmCalls, dmbCalls } = mockPages(
    t,
    Array.from({ length: 210 }, (_, i) => cm(i + 1)),
    ({ offset }) =>
      offset ? [doc(400)] : Array.from({ length: 100 }, (_, i) => doc(500 + i)),
  );
  const result = await scan();
  assert.equal(result.anchor, null);
  assert.equal(result.cmComplete, false);
  assert.deepEqual(
    cmCalls.map((body) => body.offset),
    [0, 100],
  );
  assert.deepEqual(
    dmbCalls.map((body) => body.offset),
    [0, 100],
  );
});

test("anchor 同时间组跨页时读完全部同组记录", async (t) => {
  const { cmCalls, dmbCalls } = mockPages(t, [cm(100)], ({ offset }) =>
    offset
      ? [doc(110, 4), doc(105, 4), doc(999, 3)]
      : [...Array.from({ length: 99 }, (_, i) => doc(i + 1)), doc(100, 4)],
  );
  const result = await scan();
  assert.equal(result.anchor.document_id, 100);
  assert.deepEqual(
    dmbCalls.map((body) => body.offset),
    [0, 100],
  );
  assert.equal(cmCalls.length, 1);
  assert.ok(result.documents.has(105));
  assert.ok(!result.documents.has(999));
});

test("每次扫描去重合并队列，保留已排队记录，完成后移出，再次更新可重新排队", () => {
  const first = map([doc(10), doc(20, 3)]);
  const comics = new Map([[10, cm(10)]]);
  const merged = retainPendingDocuments(
    map([doc(30, 4), doc(10)]),
    first,
    comics,
  );
  assert.deepEqual(
    entryQueue(compareLibraries(merged, comics, { full: false }).pending).map(
      (row) => row.id,
    ),
    [20, 30],
  );
  const all = retainPendingDocuments(
    map([doc(40, 2), doc(20, 3), doc(30, 4)]),
    merged,
    comics,
  );
  assert.deepEqual(
    entryQueue(compareLibraries(all, comics, { full: false }).pending).map(
      (row) => row.id,
    ),
    [40, 20, 30],
  );
  const updated = retainPendingDocuments(map([doc(10, 7)]), all, comics);
  assert.deepEqual(
    entryQueue(compareLibraries(updated, comics, { full: false }).pending).map(
      (row) => row.id,
    ),
    [40, 20, 30, 10],
  );
  assert.equal(first.size, 2);
});

test("队列按更新时间升序，同时间按 ID 升序，CM 旧记录也进入队列；清理记录仅供核对", () => {
  const documents = map([
    doc(50, 2),
    doc(10, 4),
    doc(9, 4),
    doc(1, 1, { status: "deleted" }),
    doc(2, 1, { status: "purged" }),
  ]);
  const rows = compareLibraries(
    documents,
    new Map([
      [9, { ...cm(9), updated_at: doc(9, 1).updated_at }],
      [999, cm(999)],
    ]),
  ).pending;
  assert.deepEqual(
    entryQueue(rows).map((row) => row.id),
    [50, 9, 10],
  );
  assert.equal(entryBlockReason(entryQueue(rows)[0]), null);
  const invalid = {
    id: 77,
    document: { ...documentSummary(doc(77)), updated_at: "bad" },
  };
  assert.equal(entryQueue([...rows, invalid])[0].id, 77);
  assert.match(entryBlockReason(invalid), /更新时间/);
});

test("未覆盖的历史队列显示尚未核对，不把未读取 CM 当成不存在", () => {
  const rows = compareLibraries(map([doc(9), doc(400)]), new Map(), {
    full: false,
    cmMinId: 200,
  }).pending;
  assert.deepEqual(
    rows.map((row) => [row.id, row.reason]),
    [
      [9, "unchecked"],
      [400, "missing"],
    ],
  );
});

test("DMB 乱序、重复、非法时间均报错，不返回部分队列", async (t) => {
  for (const rows of [
    [doc(1, 3), doc(2, 4)],
    [doc(1), doc(1)],
    [doc(1, 3, { updated_at: "bad" })],
  ]) {
    mockPages(t, [], () => rows);
    await assert.rejects(scan(), (error) =>
      ["INVALID_RESPONSE", "LIBRARY_CHANGED"].includes(error.code),
    );
  }
});

test("CM 分页重复、缺少总数或提前空页不会被当作完整覆盖", async (t) => {
  for (const pages of [
    [response([cm(2)])],
    [response([cm(2), cm(2)], 2)],
    [response([cm(2)], 2), response([], 2)],
    [response([cm(2)], 2), response([cm(1)], 3)],
  ]) {
    t.mock.method(globalThis, "fetch", async (url) =>
      url.startsWith("/api")
        ? pages.shift()
        : response(Array.from({ length: 100 }, (_, i) => doc(1000 + i))),
    );
    await assert.rejects(scan(), (error) =>
      ["INVALID_RESPONSE", "LIBRARY_CHANGED"].includes(error.code),
    );
  }
});

test("取消扫描同时中止两边请求，不继续下一页", async (t) => {
  const controller = new AbortController();
  const signals = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    signals.push(options.signal);
    return new Promise((resolve, reject) =>
      options.signal.addEventListener(
        "abort",
        () => reject(options.signal.reason),
        { once: true },
      ),
    );
  });
  const pending = scan({ signal: controller.signal });
  assert.equal(signals.length, 2);
  controller.abort();
  await assert.rejects(pending, { name: "AbortError" });
  assert.ok(signals.every((signal) => signal.aborted));
});

test("一边请求失败会取消另一边在途请求", async (t) => {
  let dmbSignal;
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.startsWith("/api"))
      return new Response("unavailable", { status: 503 });
    dmbSignal = options.signal;
    return new Promise((resolve, reject) =>
      options.signal.addEventListener(
        "abort",
        () => reject(options.signal.reason),
        { once: true },
      ),
    );
  });
  await assert.rejects(scan());
  assert.equal(dmbSignal.aborted, true);
});

test("录入完成按 ID 读取持久化 CM 与 DMB，不查询标题或列表", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push(url);
    assert.equal(options.method, "GET");
    assert.equal(options.body, undefined);
    if (url.startsWith("https://")) return response(doc(101));
    assert.equal(url, "/api/comics/101");
    return response({ ...cm(101), title: "已变更的本地标题" });
  });
  const result = await readEntryCompletion("https://dmb.example", 101);
  assert.equal(result.comic.id, 101);
  assert.equal(result.comic.title, "已变更的本地标题");
  assert.equal(result.document.document_id, 101);
  assert.deepEqual(calls, [
    "/api/comics/101",
    "https://dmb.example/v1/documents/101",
  ]);
});
