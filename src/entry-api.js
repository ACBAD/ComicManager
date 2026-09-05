export const DEFAULT_DMB_URL = "https://dmb.khadas.hayaseyuuka.date:8880";
export const GROUP_NAMES = {
  tag: "标签",
  property: "作品属性",
  character: "角色",
  parody: "世界观",
  expo: "展会",
  group: "社团",
  language: "语言",
};

export class ApiError extends Error {
  constructor(message, code = "NETWORK_ERROR", details = {}, status = 0) {
    super(message);
    Object.assign(this, { code, details, status });
  }
}

export async function request(
  url,
  {
    method = "GET",
    body,
    signal,
    headers = {},
    external = false,
    responseType = "json",
    redirect = "follow",
  } = {},
) {
  let response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        ...(body === undefined ? {} : { "Content-Type": "application/json" }),
        ...headers,
      },
      body: body === undefined ? undefined : JSON.stringify(body),
      credentials: external ? "omit" : "same-origin",
      cache: "no-store",
      redirect,
      signal: signal
        ? AbortSignal.any([signal, AbortSignal.timeout(30000)])
        : AbortSignal.timeout(30000),
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ApiError(
      error.name === "TimeoutError"
        ? "请求超时，请重试。"
        : "连接失败，请检查服务地址、网络或跨域配置。",
    );
  }
  let data;
  try {
    if (response.ok && responseType === "text") data = await response.text();
    else if (response.ok && responseType === "blob")
      data = await response.blob();
    else data = await response.json();
  } catch {
    throw new ApiError(
      "服务返回了无法读取的响应。",
      "INVALID_RESPONSE",
      {},
      response.status,
    );
  }
  if (!response.ok) {
    const error = data?.error;
    throw new ApiError(
      typeof error === "object"
        ? error.message
        : error || "请求未完成，请重试。",
      error?.code || `HTTP_${response.status}`,
      error?.details || {},
      response.status,
    );
  }
  return { data, headers: response.headers, status: response.status };
}

export const api = (path, options) => request("/api" + path, options);
export const query = (path, body, signal) =>
  api(path, { method: "POST", body, signal });
export function dmb(base, path, options = {}) {
  return request(base + path, {
    ...options,
    external: true,
    headers: { Authorization: "Bearer viewer" },
  });
}

export function validateDmbUrl(value) {
  const url = new URL(value);
  if (
    !["http:", "https:"].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.search ||
    url.hash
  ) {
    throw new Error("请输入不带账号、查询参数或片段的 HTTP / HTTPS 服务地址。");
  }
  return url.href.replace(/\/+$/, "");
}

export function sourceLink(value, site) {
  if (!value) return null;
  const bases = {
    hitomi: "https://hitomi.la",
    nhentai: "https://nhentai.net",
    jmcomic: "https://18comic.vip",
  };
  try {
    const url = new URL(value, bases[site]);
    return ["https:", "http:"].includes(url.protocol) &&
      !url.username &&
      !url.password
      ? url.href
      : null;
  } catch {
    return null;
  }
}

export function stableKey(value) {
  if (Array.isArray(value)) return "[" + value.map(stableKey).join(",") + "]";
  if (value && typeof value === "object") {
    return (
      "{" +
      Object.keys(value)
        .filter((key) => value[key] != null)
        .sort()
        .map((key) => JSON.stringify(key) + ":" + stableKey(value[key]))
        .join(",") +
      "}"
    );
  }
  return JSON.stringify(value);
}
export const genericKey = (tag) => JSON.stringify([tag.tag_group, tag.name]);

export function inferGroup(tag, groups) {
  if (groups.includes(tag.group)) return tag.group;
  if (tag.site === "hitomi") {
    const value = {
      groups: "group",
      characters: "character",
      parodys: "parody",
      languages: "language",
    }[tag.group];
    if (groups.includes(value)) return value;
  }
  return "";
}

export async function mapLimit(values, limit, work) {
  const results = new Array(values.length);
  let next = 0;
  await Promise.all(
    Array.from({ length: Math.min(limit, values.length) }, async () => {
      while (next < values.length) {
        const index = next++;
        results[index] = await work(values[index], index);
      }
    }),
  );
  return results;
}

export async function exactGeneric(tag, signal) {
  const { data } = await query(
    "/tags/generic/query",
    { ...tag, name_match: "exact", limit: 2 },
    signal,
  );
  if (data.length > 1)
    throw new ApiError(
      "查询到多个同名通用标签，请联系维护者。",
      "AMBIGUOUS_TAG",
    );
  return data[0] ?? null;
}

export async function ensureGeneric(tag) {
  let id = await exactGeneric(tag);
  let created = false;
  if (id === null) {
    try {
      await query("/tags/generic", tag);
      created = true;
    } catch (error) {
      if (error.code !== "GENERIC_TAG_EXISTS") throw error;
    }
    id = await exactGeneric(tag);
  }
  if (id === null) throw new ApiError("通用标签已保存但暂时无法查到，请重试。");
  return { id, created };
}

export async function exactMapping(specificTag, signal) {
  const { data } = await query(
    "/tags/specific/query",
    { match: "exact", specific_tag: specificTag },
    signal,
  );
  if (data.length > 1)
    throw new ApiError(
      "精确查询返回了多个标签，请联系维护者。",
      "AMBIGUOUS_TAG",
    );
  if (!data.length) return null;
  const { data: generic } = await api(`/tags/specific/${data[0]}/generic`, {
    signal,
  });
  return { specificId: data[0], generic };
}

export async function similarCandidates(specificTag, signal) {
  const ids = [];
  let total;
  do {
    const response = await query(
      "/tags/specific/query",
      {
        match: "same_origin",
        site: specificTag.site,
        origin_name: specificTag.origin_name,
        limit: 100,
        offset: ids.length,
      },
      signal,
    );
    total = Number(response.headers.get("X-Total-Count"));
    ids.push(...response.data);
    if (!response.data.length) break;
  } while (ids.length < total);
  const evidence = await mapLimit(ids, 3, async (id) => {
    const { data: specific } = await api(`/tags/specific/${id}`, { signal });
    const { data: generic } = await api(`/tags/specific/${id}/generic`, {
      signal,
    });
    return { specific, generic };
  });
  return mergeCandidates(evidence);
}

export function mergeCandidates(evidence) {
  const targets = new Map();
  for (const { specific, generic } of evidence) {
    const key = genericKey(generic);
    if (!targets.has(key)) targets.set(key, { generic, evidence: [] });
    targets.get(key).evidence.push(specific);
  }
  return [...targets.values()];
}
