import test from "node:test";
import assert from "node:assert/strict";
import {
  timestampNanos,
  completionReason,
  readComicLibrary,
  readDmbLibrary,
  compareLibraries,
  filterPending,
} from "../src/pending-comics.js";

const time = "2026-09-05T12:00:00.123Z";
const doc = (id, extra = {}) => ({
  document_id: id,
  title: `漫画 ${id}`,
  source: "hitomi",
  source_document_id: `source-${id}`,
  status: "archived",
  updated_at: time,
  source_meta: { title: "元数据" },
  ...extra,
});
const comic = (id, extra = {}) => ({
  id,
  title: `CM ${id}`,
  updated_at: time,
  ...extra,
});
const response = (data, total) =>
  new Response(JSON.stringify(data), {
    headers: total === undefined ? {} : { "X-Total-Count": String(total) },
  });

test("时间比较保留纳秒并统一时区", () => {
  assert.equal(
    timestampNanos(time),
    timestampNanos("2026-09-05T20:00:00.123000000+08:00"),
  );
  assert.equal(
    timestampNanos(time),
    timestampNanos("2026-09-05T07:00:00.123-05:00"),
  );
  assert.equal(
    timestampNanos("2026-09-05T12:00:00.123000001Z") - timestampNanos(time),
    1n,
  );
  assert.equal(completionReason(doc(1), comic(1)), "same_time");
  assert.equal(
    completionReason(
      doc(1),
      comic(1, { updated_at: "2026-09-05T12:00:00.123000001Z" }),
    ),
    null,
  );
  assert.equal(
    completionReason(
      doc(1, { updated_at: "2026-09-05T12:00:00.123000001Z" }),
      comic(1),
    ),
    "outdated",
  );
});

test("缺失、非法日期及无时区时间不能标记完成", () => {
  for (const value of [
    null,
    undefined,
    "",
    "not-a-date",
    "2026-02-30T12:00:00Z",
    "2026-09-05T24:00:00Z",
    "2026-09-05T12:00:00",
    "2026-09-05T12:00:00+08:99",
    123,
  ]) {
    assert.equal(timestampNanos(value), null);
    assert.equal(
      completionReason(doc(1), comic(1, { updated_at: value })),
      "unknown_time",
    );
    assert.equal(
      completionReason(doc(1, { updated_at: value }), comic(1)),
      "unknown_time",
    );
  }
  assert.equal(completionReason(doc(1), undefined), "missing");
  assert.equal(completionReason(undefined, comic(1)), "missing_source");
});

test("按 DMB document_id 与 CM id 对应，保留未入库、过期及 CM 独有记录", () => {
  const documents = new Map(
    [doc(1, { source_document_id: "9" }), doc(2), doc(3), doc(4)].map(
      (value) => [value.document_id, value],
    ),
  );
  const comics = new Map(
    [
      comic(1, { updated_at: "2026-09-06T00:00:00Z" }),
      comic(2, { updated_at: "2026-09-04T00:00:00Z" }),
      comic(4),
      comic(9),
    ].map((value) => [value.id, value]),
  );
  const result = compareLibraries(documents, comics);
  assert.equal(result.completed, 1);
  assert.equal(result.dmbTotal, 4);
  assert.equal(result.cmTotal, 4);
  assert.deepEqual(
    result.pending.map(({ id, reason }) => [id, reason]),
    [
      [9, "missing_source"],
      [2, "outdated"],
      [3, "missing"],
      [4, "same_time"],
    ],
  );
  assert.deepEqual(compareLibraries(new Map(), new Map()), {
    pending: [],
    completed: 0,
    dmbTotal: 0,
    cmTotal: 0,
  });
});

test("搜索与原因、DMB 状态筛选可组合使用", () => {
  const rows = compareLibraries(
    new Map([
      [1, doc(1, { title: "Blue 漫画", status: "failed" })],
      [2, doc(2)],
    ]),
    new Map([[3, comic(3)]]),
  ).pending;
  assert.deepEqual(
    filterPending(rows, {
      search: " blue ",
      reason: "missing",
      status: "failed",
    }).map((row) => row.id),
    [1],
  );
  assert.deepEqual(
    filterPending(rows, { search: "source-2" }).map((row) => row.id),
    [2],
  );
  assert.deepEqual(
    filterPending(rows, { status: "missing_source" }).map((row) => row.id),
    [3],
  );
  assert.deepEqual(filterPending(rows, { reason: "outdated" }), []);
});

test("读取全部 CM 分页，列表缓存只保留对照所需字段", async (t) => {
  const calls = [],
    progress = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, method: options.method });
    return response(
      calls.length === 1
        ? Array.from({ length: 100 }, (_, i) =>
            comic(i + 1, { comic_tags: ["large metadata"] }),
          )
        : [comic(101), comic(102)],
      102,
    );
  });
  const result = await readComicLibrary({
    onProgress: (state) => progress.push(state),
  });
  assert.equal(result.size, 102);
  assert.deepEqual(calls, [
    { url: "/api/comics?limit=100&offset=0", method: "GET" },
    { url: "/api/comics?limit=100&offset=100", method: "GET" },
  ]);
  assert.deepEqual(result.get(1), comic(1));
  assert.deepEqual(progress, [
    { loaded: 100, total: 102 },
    { loaded: 102, total: 102 },
  ]);
});

test("CM 不完整响应、分页变化或重复不能当作完整扫描", async (t) => {
  const cases = [
    ["没有总数", [response([comic(1)])]],
    ["总数改变", [response([comic(1)], 2), response([comic(2)], 3)]],
    ["提前空页", [response([comic(1)], 2), response([], 2)]],
    ["重复 ID", [response([comic(1)], 2), response([comic(1)], 2)]],
    ["响应不是数组", [response({}, 1)]],
    ["ID 不合法", [response([{ id: "1" }], 1)]],
  ];
  for (const [name, pages] of cases)
    await t.test(name, async (t) => {
      t.mock.method(globalThis, "fetch", async () => pages.shift());
      await assert.rejects(readComicLibrary(), (error) =>
        ["INVALID_RESPONSE", "LIBRARY_CHANGED"].includes(error.code),
      );
    });
});

test("DMB 遍历活动、删除与清理记录，跨状态重复保留较新数据", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const body = JSON.parse(options.body);
    calls.push(body);
    assert.equal(url, "https://dmb.example/v1/documents/query");
    assert.equal(options.headers.Authorization, "Bearer viewer");
    assert.equal(body.order, "ASC");
    assert.equal(body.orderby, "id");
    assert.equal(body.limit, 100);
    if (body.mode === "all")
      return response(
        body.offset === 0
          ? Array.from({ length: 100 }, (_, i) => doc(i + 1))
          : [doc(101)],
      );
    if (body.params.status === "deleted")
      return response([
        doc(1, { status: "deleted", updated_at: "2026-09-06T00:00:00Z" }),
        doc(202, { status: "deleted" }),
      ]);
    return response([doc(303, { status: "purged" })]);
  });
  const result = await readDmbLibrary("https://dmb.example");
  assert.equal(result.size, 103);
  assert.equal(result.get(1).status, "deleted");
  assert.equal(result.get(1).has_metadata, true);
  assert.equal("source_meta" in result.get(1), false);
  assert.deepEqual(
    calls.map((call) => [call.mode, call.offset, call.params?.status]),
    [
      ["all", 0, undefined],
      ["all", 100, undefined],
      ["by_status", 0, "deleted"],
      ["by_status", 0, "purged"],
    ],
  );
});

test("停止扫描后不继续请求后续分页", async (t) => {
  for (const source of ["CM", "DMB"])
    await t.test(source, async (t) => {
      const controller = new AbortController();
      let calls = 0;
      t.mock.method(globalThis, "fetch", async () => {
        calls++;
        return response(
          source === "CM"
            ? [comic(1)]
            : Array.from({ length: 100 }, (_, i) => doc(i)),
          2,
        );
      });
      const options = {
        signal: controller.signal,
        onProgress: () => controller.abort(),
      };
      await assert.rejects(
        source === "CM"
          ? readComicLibrary(options)
          : readDmbLibrary("https://dmb.example", options),
        (error) => error.name === "AbortError",
      );
      assert.equal(calls, 1);
    });
});

test("某页读取失败时拒绝返回部分结果", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () =>
    ++calls === 1
      ? response([comic(1)], 2)
      : new Response(
          JSON.stringify({
            error: { code: "FORBIDDEN", message: "权限不足", details: {} },
          }),
          { status: 403 },
        ),
  );
  await assert.rejects(
    readComicLibrary(),
    (error) => error.code === "FORBIDDEN",
  );
});
