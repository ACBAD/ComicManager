import test from "node:test";
import assert from "node:assert/strict";
import {
  ApiError,
  request,
  ensureGeneric,
  exactMapping,
  similarCandidates,
  stableKey,
  inferGroup,
  mapLimit,
  mergeCandidates,
  sourceLink,
  validateDmbUrl,
} from "../src/entry-api.js";

const generic = { tag_group: "tag", name: "glasses" };
const female = {
  site: "hitomi",
  origin_name: "glasses",
  group: "tags",
  tag_sex: "female",
  url: "/tag/female:glasses.html",
};
const male = { ...female, tag_sex: "male", url: "/tag/male:glasses.html" };
const response = (data, status = 200, headers = {}) =>
  new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json", ...headers },
  });

test("标签身份忽略字段顺序和省略的 null，但保留来源、性别与 URL 差异", () => {
  assert.equal(
    stableKey({ site: "hitomi", origin_name: "a", group: "tags", url: null }),
    stableKey({ group: "tags", origin_name: "a", site: "hitomi" }),
  );
  assert.notEqual(stableKey(female), stableKey(male));
  assert.notEqual(
    stableKey(female),
    stableKey({ ...female, url: "/different.html" }),
  );
  assert.notEqual(stableKey(female), stableKey({ ...female, site: "nhentai" }));
});

test("无法确定的来源分组保持未选择，不默认归入 tag", () => {
  const groups = [
    "tag",
    "property",
    "character",
    "parody",
    "expo",
    "group",
    "language",
  ];
  assert.equal(
    inferGroup({ site: "hitomi", group: "characters" }, groups),
    "character",
  );
  assert.equal(
    inferGroup({ site: "hitomi", group: "groups" }, groups),
    "group",
  );
  assert.equal(inferGroup({ site: "hitomi", group: "tags" }, groups), "");
  assert.equal(
    inferGroup({ site: "hitomi", group: "unrecognized" }, groups),
    "",
  );
});

test("同一通用标签只显示一个候选，同时保留 male/female 两条证据", () => {
  const property = { tag_group: "property", name: "glasses" };
  const candidates = mergeCandidates([
    { specific: female, generic },
    { specific: male, generic: { ...generic } },
    { specific: male, generic: property },
  ]);
  assert.equal(candidates.length, 2);
  assert.deepEqual(candidates[0].evidence, [female, male]);
  assert.deepEqual(candidates[1].generic, property);
});

test("有限并发在乱序完成时保持结果顺序且不超过上限", async () => {
  let active = 0,
    maximum = 0;
  const result = await mapLimit(
    Array.from({ length: 18 }, (_, i) => i),
    6,
    async (index) => {
      active++;
      maximum = Math.max(maximum, active);
      await new Promise((resolve) => setTimeout(resolve, (index % 3) + 1));
      active--;
      return index * 2;
    },
  );
  assert.equal(maximum, 6);
  assert.deepEqual(
    result,
    Array.from({ length: 18 }, (_, i) => i * 2),
  );
});

test("同名创建并发冲突时精确重查 ID，不重复创建或假定创建响应含 ID", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push({ url, body: JSON.parse(options.body) });
    if (calls.length === 1) return response([]);
    if (calls.length === 2)
      return response(
        {
          error: { code: "GENERIC_TAG_EXISTS", message: "已存在", details: {} },
        },
        409,
      );
    return response([42]);
  });
  assert.deepEqual(await ensureGeneric(generic), { id: 42, created: false });
  assert.deepEqual(
    calls.map((call) => call.url),
    ["/api/tags/generic/query", "/api/tags/generic", "/api/tags/generic/query"],
  );
  assert.deepEqual(calls[1].body, generic);
});

test("成功创建后仍通过查询接口取得 ID", async (t) => {
  const bodies = [response([]), response(generic, 201), response([9])];
  t.mock.method(globalThis, "fetch", async () => bodies.shift());
  assert.deepEqual(await ensureGeneric(generic), { id: 9, created: true });
});

test("创建权限错误不能当作重复记录吞掉", async (t) => {
  let count = 0;
  t.mock.method(globalThis, "fetch", async () =>
    ++count === 1
      ? response([])
      : response(
          { error: { code: "FORBIDDEN", message: "权限不足", details: {} } },
          403,
        ),
  );
  await assert.rejects(
    ensureGeneric(generic),
    (error) => error.code === "FORBIDDEN" && error.status === 403,
  );
  assert.equal(count, 2);
});

test("精确映射读取 ID 后单独查询关系，不接受多条精确匹配", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url) => {
    calls.push(url);
    return response(calls.length === 1 ? [17] : generic);
  });
  assert.deepEqual(await exactMapping(female), { specificId: 17, generic });
  assert.deepEqual(calls, [
    "/api/tags/specific/query",
    "/api/tags/specific/17/generic",
  ]);
  t.mock.method(globalThis, "fetch", async () => response([17, 18]));
  await assert.rejects(
    exactMapping(female),
    (error) => error.code === "AMBIGUOUS_TAG",
  );
});

test("same_origin 翻页读取全部证据，按通用标签身份合并候选", async (t) => {
  const offsets = [];
  t.mock.method(globalThis, "fetch", async (url, options) => {
    if (url.endsWith("/query")) {
      const offset = JSON.parse(options.body).offset;
      offsets.push(offset);
      return response(offset === 0 ? [1] : [2], 200, { "X-Total-Count": "2" });
    }
    return response(
      url.endsWith("/generic") ? generic : url.endsWith("/1") ? female : male,
    );
  });
  const result = await similarCandidates(female);
  assert.deepEqual(offsets, [0, 1]);
  assert.deepEqual(result, [{ generic, evidence: [female, male] }]);
});

test("来源链接阻止可执行协议和嵌入凭据", () => {
  assert.equal(
    sourceLink("/tag/a.html", "hitomi"),
    "https://hitomi.la/tag/a.html",
  );
  for (const unsafe of [
    "javascript:alert(1)",
    "data:text/html,test",
    "https://user:password@example.com/a",
  ])
    assert.equal(sourceLink(unsafe, "hitomi"), null);
  assert.equal(
    validateDmbUrl("https://dmb.example.com:8880/"),
    "https://dmb.example.com:8880",
  );
  assert.throws(() => validateDmbUrl("https://user:password@example.com"));
  assert.throws(() => validateDmbUrl("javascript:alert(1)"));
});

test("请求取消保留 AbortError，网络失败提供可恢复错误", async (t) => {
  const controller = new AbortController();
  controller.abort();
  t.mock.method(globalThis, "fetch", async () => {
    throw new DOMException("cancelled", "AbortError");
  });
  await assert.rejects(
    request("/api/tags/groups", { signal: controller.signal }),
    (error) => error.name === "AbortError",
  );
  t.mock.method(globalThis, "fetch", async () => {
    throw new TypeError("Failed to fetch");
  });
  await assert.rejects(
    request("/api/tags/groups"),
    (error) => error instanceof ApiError && error.code === "NETWORK_ERROR",
  );
});
