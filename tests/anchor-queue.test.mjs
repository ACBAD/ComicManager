import test from "node:test";
import assert from "node:assert/strict";
import {
  readDmbUntilAnchor,
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
const response = (data) => new Response(JSON.stringify(data));
const map = (rows) =>
  new Map(rows.map((row) => [row.document_id, documentSummary(row)]));
const scan = (comics = new Map(), options) =>
  readDmbUntilAnchor("https://dmb.example", comics, options);

test("从最新更新时间开始，首次遇到 CM 完成记录后停止，不把未扫描 CM 当作来源缺失", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push(JSON.parse(options.body));
    return response([doc(10), doc(20, 4), doc(30, 3), doc(40, 2)]);
  });
  const comics = new Map([
    [30, cm(30)],
    [999, cm(999)],
  ]);
  const result = await scan(comics);
  assert.equal(result.anchor.document_id, 30);
  assert.deepEqual([...result.documents.keys()], [10, 20, 30]);
  assert.deepEqual(
    entryQueue(
      compareLibraries(result.documents, comics, { full: false }).pending,
    ).map((row) => row.id),
    [20, 10],
  );
  assert.deepEqual(calls, [
    {
      mode: "all",
      limit: 100,
      offset: 0,
      orderby: "updated_at",
      order: "DESC",
    },
  ]);
});

test("CM 同时间或比来源更旧均不能作为 anchor，没有 anchor 时读取全部分页", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const { offset } = JSON.parse(options.body);
    calls.push(offset);
    return response(
      offset
        ? [doc(101, 4)]
        : Array.from({ length: 100 }, (_, i) => doc(i + 1)),
    );
  });
  const result = await scan(
    new Map([
      [1, { ...cm(1), updated_at: doc(1).updated_at }],
      [2, { ...cm(2), updated_at: doc(2, 3).updated_at }],
    ]),
  );
  assert.equal(result.anchor, null);
  assert.equal(result.documents.size, 101);
  assert.deepEqual(calls, [0, 100]);
});

test("anchor 同时间组跨页时读完全部同组记录，无关 ID 顺序不会遗漏", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const { offset } = JSON.parse(options.body);
    calls.push(offset);
    return response(
      offset
        ? [doc(110, 4), doc(105, 4), doc(999, 3)]
        : [...Array.from({ length: 99 }, (_, i) => doc(i + 1)), doc(100, 4)],
    );
  });
  const result = await scan(new Map([[100, cm(100)]]));
  assert.equal(result.anchor.document_id, 100);
  assert.deepEqual(calls, [0, 100]);
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

test("扫描乱序、重复、非法时间均报错，不返回部分队列", async (t) => {
  for (const rows of [
    [doc(1, 3), doc(2, 4)],
    [doc(1), doc(1)],
    [doc(1, 3, { updated_at: "bad" })],
  ]) {
    t.mock.method(globalThis, "fetch", async () => response(rows));
    await assert.rejects(scan(), (error) =>
      ["INVALID_RESPONSE", "LIBRARY_CHANGED"].includes(error.code),
    );
  }
});

test("取消或分页错误不继续扫描，也不修改传入 CM", async (t) => {
  const controller = new AbortController();
  let calls = 0;
  const comics = new Map([[999, cm(999)]]);
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    controller.abort();
    return response([doc(1)]);
  });
  await assert.rejects(scan(comics, { signal: controller.signal }), {
    name: "AbortError",
  });
  assert.equal(calls, 1);
  assert.equal(comics.size, 1);
});

test("录入完成必须读到持久化的 CM 时间；同名漫画需按 ID 查找并继续翻页", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push(url);
    if (url.startsWith("https://")) return response(doc(101));
    const body = JSON.parse(options.body);
    assert.equal(body.title_match, "exact");
    return response(
      body.offset
        ? [cm(101)]
        : Array.from({ length: 100 }, (_, i) => cm(i + 1)),
    );
  });
  const result = await readEntryCompletion(
    "https://dmb.example",
    101,
    "comic 101",
  );
  assert.equal(result.comic.id, 101);
  assert.equal(result.document.document_id, 101);
  assert.equal(calls.filter((url) => url === "/api/comics/query").length, 2);
});
