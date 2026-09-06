import test from "node:test";
import assert from "node:assert/strict";
import { runBatchEntry } from "../src/batch-entry.js";
import { stableKey, genericKey } from "../src/entry-api.js";
import { entryQueue } from "../src/pending-comics.js";

const groups = ["tag", "group", "character"];
const tag = (name, group = "tags", extra = {}) => ({
  site: "hitomi",
  group,
  origin_name: name,
  ...extra,
});
const groupTag = (name, extra = {}) => tag(name, "groups", extra);
const row = (id, extra = {}) => ({
  id,
  document: {
    title: `comic ${id}`,
    source: "hitomi",
    has_metadata: true,
    status: "archived",
    updated_at: "2026-09-04T00:00:00Z",
  },
  ...extra,
});
const response = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), { status, headers });
const failure = (code, status = 409) =>
  response({ error: { code, message: code } }, status);

function server(t, documents, { mapped = [], generics = [], intercept } = {}) {
  const calls = [];
  const mappings = new Map();
  const genericTags = new Map();
  let nextId = 10;
  const addGeneric = (generic) => {
    const key = genericKey(generic);
    if (!genericTags.has(key)) genericTags.set(key, { id: nextId++, generic });
    return genericTags.get(key).id;
  };
  for (const generic of generics) addGeneric(generic);
  for (const specific of mapped) {
    const generic = {
      tag_group: specific.group === "groups" ? "group" : "tag",
      name: specific.origin_name,
    };
    const genericId = addGeneric(generic);
    mappings.set(stableKey(specific), { id: nextId++, specific, genericId });
  }
  t.mock.method(globalThis, "fetch", async (url, options) => {
    const body = options.body ? JSON.parse(options.body) : null;
    calls.push({ url, body });
    const intercepted = await intercept?.(url, body);
    if (intercepted) return intercepted;
    let match;
    if ((match = url.match(/^\/api\/comics\/(\d+)\/preview$/)))
      return response({
        id: Number(match[1]),
        comic_tags: documents[match[1]],
      });
    if (url === "/api/tags/specific/query") {
      const mapping = mappings.get(stableKey(body.specific_tag));
      return response(mapping ? [mapping.id] : []);
    }
    if ((match = url.match(/^\/api\/tags\/specific\/(\d+)\/generic$/))) {
      const mapping = [...mappings.values()].find(
        (value) => value.id === Number(match[1]),
      );
      return response(
        [...genericTags.values()].find(
          (value) => value.id === mapping.genericId,
        ).generic,
      );
    }
    if (url === "/api/tags/generic/query") {
      const generic = genericTags.get(genericKey(body));
      return response(generic ? [generic.id] : []);
    }
    if (url === "/api/tags/generic") {
      addGeneric(body);
      return response(body, 201);
    }
    if (url === "/api/tags/specific") {
      mappings.set(stableKey(body.specific_tag), {
        id: nextId++,
        specific: body.specific_tag,
        genericId: body.generic_tag_id,
      });
      return response(body.specific_tag, 201);
    }
    if ((match = url.match(/^\/api\/comics\/(\d+)\/commit(?:\?.*)?$/)))
      return response(
        { id: Number(match[1]), title: `comic ${match[1]}` },
        201,
      );
    if ((match = url.match(/^\/api\/comics\/(\d+)$/))) {
      const id = Number(match[1]);
      return response({
        id,
        title: `comic ${id}`,
        updated_at: "2026-09-06T00:00:00Z",
      });
    }
    if ((match = url.match(/^https:\/\/dmb.example\/v1\/documents\/(\d+)$/)))
      return response({
        document_id: Number(match[1]),
        ...row(Number(match[1])).document,
        source_meta: { title: "metadata" },
      });
    throw new Error(`Unexpected API: ${url}`);
  });
  return {
    calls,
    writes: () =>
      calls.filter(
        ({ url }) =>
          /\/commit$/.test(url) ||
          ["/api/tags/generic", "/api/tags/specific"].includes(url),
      ),
  };
}

async function run(records, extra = {}) {
  const results = [];
  const outcome = await runBatchEntry(records, {
    groups,
    dmbUrl: "https://dmb.example",
    onResult: (result) => results.push(result),
    ...extra,
  });
  return { results, outcome };
}

test("依次直接提交、创建或复用 group，遇到非 group 缺失停在当前部", async (t) => {
  const mapped = tag("mapped");
  const groupA = groupTag("new circle", { url: "/a" });
  const groupB = groupTag("new circle", { url: "/b" });
  const existing = groupTag("existing circle");
  const untouched = groupTag("must not create");
  const api = server(
    t,
    {
      1: [mapped],
      2: [mapped, groupA, groupB, groupA],
      3: [existing],
      4: [untouched, tag("missing")],
      5: [mapped],
    },
    {
      mapped: [mapped],
      generics: [{ tag_group: "group", name: "existing circle" }],
    },
  );
  const { results } = await run([1, 2, 3, 4, 5].map((id) => row(id)));
  assert.deepEqual(
    results.map((value) => value.status),
    ["success", "success", "success", "blocked"],
  );
  assert.deepEqual(
    api.calls
      .filter(({ url }) => url === "/api/tags/generic")
      .map(({ body }) => body),
    [{ tag_group: "group", name: "new circle" }],
  );
  assert.equal(
    api.calls.filter(({ url }) => url === "/api/tags/specific").length,
    3,
  );
  const commits = api.calls.filter(({ url }) => url.endsWith("/commit"));
  assert.deepEqual(
    commits.map(({ url }) => url),
    [1, 2, 3].map((id) => `/api/comics/${id}/commit`),
  );
  for (const call of commits) assert.equal(call.body, null);
  assert.equal(
    api.writes().some(({ body }) => body?.name === "must not create"),
    false,
  );
  const firstCommit = api.calls.findIndex(
    ({ url }) => url === "/api/comics/1/commit",
  );
  assert.ok(
    firstCommit <
      api.calls.findIndex(({ url }) => url === "/api/comics/2/preview"),
  );
});

test("队列涵盖所有分页，已有但未完成的漫画也按顺序更新", async (t) => {
  const all = Array.from({ length: 25 }, (_, index) => row(index + 1));
  all.push(
    row(30, { comic: { id: 30 } }),
    row(31, { document: null, comic: { id: 31 } }),
  );
  const candidates = entryQueue(all);
  assert.equal(candidates.length, 26);
  const api = server(
    t,
    Object.fromEntries(candidates.map(({ id }) => [id, []])),
  );
  const { results } = await run(candidates);
  assert.equal(
    results.filter((result) => result.status === "success").length,
    26,
  );
  assert.equal(
    api.calls.some(
      ({ url }) => url === "/api/comics/30/commit?allow_override=true",
    ),
    true,
  );
});

test("非 group 和未知来源分类会阻断队列，整部没有标签写入或 commit", async (t) => {
  const api = server(t, {
    1: [groupTag("circle"), tag("x", "characters")],
    2: [tag("circle", "unknown")],
  });
  const { results } = await run([row(1), row(2)]);
  assert.ok(results.every((result) => result.status === "blocked"));
  assert.deepEqual(api.writes(), []);
});

test("弱 ETag 或缺少 ETag 都不影响批量录入", async (t) => {
  const api = server(
    t,
    { 1: [], 2: [] },
    {
      intercept: (url) =>
        url === "/api/comics/1/preview"
          ? response({ id: 1, comic_tags: [] }, 200, {
              ETag: 'W/"proxy-value"',
            })
          : null,
    },
  );
  const { results } = await run([row(1), row(2)]);
  assert.ok(results.every((result) => result.status === "success"));
  assert.ok(
    api.calls
      .filter(({ url }) => url.endsWith("/commit"))
      .every(({ body }) => body === null),
  );
});

test("标签查询失败不能当成未映射来创建，也不能继续下一部", async (t) => {
  const broken = groupTag("broken");
  const api = server(
    t,
    { 1: [broken], 2: [] },
    {
      intercept: (url, body) =>
        url === "/api/tags/specific/query" &&
        body.specific_tag.origin_name === "broken"
          ? failure("NETWORK_ERROR", 502)
          : null,
    },
  );
  const { results } = await run([row(1), row(2)]);
  assert.deepEqual(
    results.map((value) => value.status),
    ["failed"],
  );
  assert.deepEqual(
    api.writes().map(({ url }) => url),
    [],
  );
});

test("group 映射冲突时当前部不提交，后续漫画保持等待", async (t) => {
  const api = server(
    t,
    { 1: [groupTag("conflict")], 2: [] },
    {
      intercept: (url) =>
        url === "/api/tags/specific"
          ? failure("SPECIFIC_TAG_MAPPING_CONFLICT")
          : null,
    },
  );
  const { results } = await run([row(1), row(2)]);
  assert.deepEqual(
    results.map((value) => value.status),
    ["blocked"],
  );
  assert.deepEqual(
    api.calls
      .filter(({ url }) => url.endsWith("/commit"))
      .map(({ url }) => url),
    [],
  );
});

test("最新来源存在未映射标签时停住，不自动重试或覆盖", async (t) => {
  const api = server(
    t,
    { 1: [], 2: [], 3: [] },
    {
      intercept: (url) =>
        url === "/api/comics/1/commit"
          ? failure("UNMAPPED_SPECIFIC_TAGS")
          : url === "/api/comics/2/commit"
            ? failure("COMIC_ALREADY_EXISTS")
            : null,
    },
  );
  const { results } = await run([row(1), row(2), row(3)]);
  assert.deepEqual(
    results.map((value) => value.status),
    ["blocked"],
  );
  assert.equal(
    api.calls.filter(({ url }) => url.endsWith("/preview")).length,
    1,
  );
});

test("停止请求完成当前漫画后生效，不开始下一部", async (t) => {
  let stopping = false;
  const api = server(
    t,
    { 1: [groupTag("current")], 2: [] },
    {
      intercept: (url) => {
        if (url === "/api/tags/specific") stopping = true;
      },
    },
  );
  const { results, outcome } = await run([row(1), row(2)], {
    shouldStop: () => stopping,
  });
  assert.deepEqual(
    results.map(({ id, status }) => [id, status]),
    [[1, "success"]],
  );
  assert.equal(outcome.stopped, true);
  assert.equal(
    api.calls.some(({ url }) => url === "/api/comics/2/preview"),
    false,
  );
});

test("权限错误停止整批，避免继续请求其他漫画", async (t) => {
  const api = server(
    t,
    { 1: [], 2: [] },
    {
      intercept: (url) =>
        url.endsWith("/commit") ? failure("FORBIDDEN", 403) : null,
    },
  );
  const { results, outcome } = await run([row(1), row(2)]);
  assert.equal(results[0].status, "failed");
  assert.equal(outcome.stopped, true);
  assert.equal(
    api.calls.some(({ url }) => url === "/api/comics/2/preview"),
    false,
  );
});

test("来源不可用时停在队首，不读取后续预览", async (t) => {
  const api = server(t, {});
  const { results, outcome } = await run([
    row(1, { document: { ...row(1).document, has_metadata: false } }),
    row(2),
  ]);
  assert.deepEqual(
    results.map(({ id, status }) => [id, status]),
    [[1, "blocked"]],
  );
  assert.equal(outcome.stopped, true);
  assert.deepEqual(api.calls, []);
});

test("失败、删除和清理记录不参与自动录入，也不阻挡后续有效漫画", async (t) => {
  const api = server(t, { 4: [] });
  const records = ["failed", "deleted", "purged"].map((status, index) =>
    row(index + 1, { document: { ...row(index + 1).document, status } }),
  );
  const { results } = await run([...records, row(4)]);
  assert.deepEqual(
    results.map((result) => [result.id, result.status]),
    [[4, "success"]],
  );
  assert.equal(
    api.calls.some(({ url }) => /\/comics\/[123](?:\/|$)/.test(url)),
    false,
  );
});

test("并发录入冲突仍停在当前部，刷新确认后才能继续", async (t) => {
  const api = server(
    t,
    { 1: [], 2: [] },
    {
      intercept: (url) =>
        url === "/api/comics/1/commit" ? failure("COMIC_ALREADY_EXISTS") : null,
    },
  );
  const { results, outcome } = await run([row(1), row(2)]);
  assert.equal(results[0].status, "blocked");
  assert.equal(outcome.stopped, true);
  assert.ok(!api.calls.some(({ url }) => url.includes("/2/")));
});

test("输入顺序不能改变按更新时间录入的顺序", async (t) => {
  const api = server(t, { 1: [], 2: [], 3: [] });
  await run([
    row(1, {
      document: { ...row(1).document, updated_at: "2026-09-05T00:00:00Z" },
    }),
    row(3),
    row(2),
  ]);
  assert.deepEqual(
    api.calls
      .filter(({ url }) => url.endsWith("/commit"))
      .map(({ url }) => url),
    [2, 3, 1].map((id) => `/api/comics/${id}/commit`),
  );
});

test("提交成功但 CM 时间不晚于 DMB，保留当前部并停止", async (t) => {
  const api = server(
    t,
    { 1: [], 2: [] },
    {
      intercept: (url) =>
        url === "https://dmb.example/v1/documents/1"
          ? response({
              document_id: 1,
              ...row(1).document,
              updated_at: "2026-09-07T00:00:00Z",
            })
          : null,
    },
  );
  const { results, outcome } = await run([row(1), row(2)]);
  assert.equal(results[0].status, "blocked");
  assert.equal(outcome.stopped, true);
  assert.ok(!api.calls.some(({ url }) => url.includes("/2/")));
});
