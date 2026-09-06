import test from "node:test";
import assert from "node:assert/strict";
import { batchEntryCandidates, runBatchEntry } from "../src/batch-entry.js";
import { stableKey, genericKey } from "../src/entry-api.js";
import { filterPending } from "../src/pending-comics.js";

const groups = ["tag", "group", "character"];
const revision = `sha256:${"a".repeat(64)}`;
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
      return response(
        { id: Number(match[1]), comic_tags: documents[match[1]] },
        200,
        { ETag: `"${revision}"` },
      );
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
    if (/^\/api\/comics\/\d+\/commit$/.test(url)) return response({}, 201);
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
    onResult: (result) => results.push(result),
    ...extra,
  });
  return { results, outcome };
}

test("整批依次直接提交、创建 group、复用同名 group、跳过混合缺失后继续下一部", async (t) => {
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
    ["success", "success", "success", "skipped", "success"],
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
    [1, 2, 3, 5].map((id) => `/api/comics/${id}/commit`),
  );
  for (const call of commits)
    assert.deepEqual(call.body, { source_revision: revision });
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

test("当前筛选的全部未入库结果进入队列，不只取第一页，不覆盖已有 CM", async (t) => {
  const all = Array.from({ length: 25 }, (_, index) => row(index + 1));
  all.push(
    row(30, { comic: { id: 30 } }),
    row(31, { document: null, comic: { id: 31 } }),
  );
  const candidates = batchEntryCandidates(
    filterPending(all, { search: "comic" }),
  );
  assert.equal(candidates.length, 25);
  const api = server(
    t,
    Object.fromEntries(candidates.map(({ id }) => [id, []])),
  );
  const { results } = await run(candidates);
  assert.equal(
    results.filter((result) => result.status === "success").length,
    25,
  );
  assert.equal(
    api.calls.some(({ url }) => url.includes("override")),
    false,
  );
});

test("非 group 和未知来源分类跳过，整部没有标签写入或 commit", async (t) => {
  const api = server(t, {
    1: [groupTag("circle"), tag("x", "characters")],
    2: [tag("circle", "unknown")],
  });
  const { results } = await run([row(1), row(2)]);
  assert.ok(results.every((result) => result.status === "skipped"));
  assert.deepEqual(api.writes(), []);
});

test("标签查询失败不能当成未映射来创建，失败后继续下一部", async (t) => {
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
    ["failed", "success"],
  );
  assert.deepEqual(
    api.writes().map(({ url }) => url),
    ["/api/comics/2/commit"],
  );
});

test("group 映射冲突时当前部不提交，后续漫画仍继续", async (t) => {
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
    ["skipped", "success"],
  );
  assert.deepEqual(
    api.calls
      .filter(({ url }) => url.endsWith("/commit"))
      .map(({ url }) => url),
    ["/api/comics/2/commit"],
  );
});

test("来源版本变化或并发已入库都跳过，不自动刷新重试或覆盖", async (t) => {
  const api = server(
    t,
    { 1: [], 2: [], 3: [] },
    {
      intercept: (url) =>
        url === "/api/comics/1/commit"
          ? failure("SOURCE_META_CHANGED")
          : url === "/api/comics/2/commit"
            ? failure("COMIC_ALREADY_EXISTS")
            : null,
    },
  );
  const { results } = await run([row(1), row(2), row(3)]);
  assert.deepEqual(
    results.map((value) => value.status),
    ["skipped", "skipped", "success"],
  );
  assert.equal(
    api.calls.filter(({ url }) => url.endsWith("/preview")).length,
    3,
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

test("来源不可用及已有漫画直接跳过，不读取预览", async (t) => {
  const api = server(t, {});
  const { results } = await run([
    row(1, { comic: { id: 1 } }),
    row(2, { document: null }),
    row(3, { document: { status: "deleted" } }),
    row(4, { document: { source: "unknown", has_metadata: true } }),
    row(5, { document: { source: "hitomi", has_metadata: false } }),
  ]);
  assert.ok(results.every((value) => value.status === "skipped"));
  assert.deepEqual(api.calls, []);
});
