import { ApiError, api, dmb } from "./entry-api.js";

export const PENDING_REASONS = {
  missing: "未入库",
  outdated: "需要更新",
  same_time: "更新时间相同",
  unknown_time: "时间无法比较",
  missing_source: "DMB 无对应记录",
  unchecked: "CM 尚未核对",
};
export const DMB_STATUSES = {
  queued: "排队中",
  resolving: "解析中",
  downloading: "下载中",
  archived: "已归档",
  failed: "归档失败",
  deleted: "已删除",
  purged: "已清理",
};

// DMB 使用纳秒精度，CM 使用毫秒精度；统一时区后比较，保留小数秒。
export function timestampNanos(value) {
  if (typeof value !== "string") return null;
  const match = value.match(
    /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})(?:\.(\d{1,9}))?(Z|([+-])(\d{2}):(\d{2}))$/,
  );
  if (!match) return null;
  const wallTime = `${match[1]}T${match[2]}`;
  const wallMillis = Date.parse(wallTime + "Z");
  if (
    !Number.isFinite(wallMillis) ||
    new Date(wallMillis).toISOString().slice(0, 19) !== wallTime
  )
    return null;
  const hours = Number(match[6] || 0),
    minutes = Number(match[7] || 0);
  if (hours > 23 || minutes > 59) return null;
  const offset = (hours * 60 + minutes) * (match[5] === "-" ? -1 : 1);
  return (
    BigInt(wallMillis - offset * 60000) * 1000000n +
    BigInt((match[3] || "").padEnd(9, "0"))
  );
}

export function completionReason(document, comic) {
  if (!document) return "missing_source";
  if (!comic) return "missing";
  const sourceTime = timestampNanos(document.updated_at);
  const localTime = timestampNanos(comic.updated_at);
  if (sourceTime === null || localTime === null) return "unknown_time";
  if (localTime > sourceTime) return null;
  return localTime === sourceTime ? "same_time" : "outdated";
}

export function documentSummary(document) {
  return {
    document_id: document.document_id,
    title: document.title,
    source: document.source,
    source_document_id: document.source_document_id,
    status: document.status,
    updated_at: document.updated_at,
    has_metadata:
      !!document.source_meta && Object.keys(document.source_meta).length > 0,
  };
}

function validateRecords(records, key, service) {
  if (
    !Array.isArray(records) ||
    records.some(
      (row) => !row || !Number.isSafeInteger(row[key]) || row[key] < 0,
    )
  )
    throw new ApiError(`${service} 返回了无效的记录列表。`, "INVALID_RESPONSE");
}

export async function readComicLibrary({ signal, onProgress = () => {} } = {}) {
  const records = new Map();
  let offset = 0,
    total = null;
  do {
    signal?.throwIfAborted();
    const response = await api(`/comics?limit=100&offset=${offset}`, {
      signal,
    });
    validateRecords(response.data, "id", "CM");
    const totalHeader = response.headers.get("X-Total-Count");
    if (
      !/^\d+$/.test(totalHeader || "") ||
      !Number.isSafeInteger(Number(totalHeader))
    )
      throw new ApiError(
        "CM 未返回有效总数，无法确认是否已读取全部漫画。",
        "INVALID_RESPONSE",
      );
    const currentTotal = Number(totalHeader);
    if (total !== null && currentTotal !== total)
      throw new ApiError(
        "CM 库在扫描期间发生了变化，请重新扫描。",
        "LIBRARY_CHANGED",
      );
    total = currentTotal;
    for (const comic of response.data) {
      if (records.has(comic.id))
        throw new ApiError(
          "CM 分页中出现重复记录，请重新扫描。",
          "LIBRARY_CHANGED",
        );
      records.set(comic.id, {
        id: comic.id,
        title: comic.title,
        updated_at: comic.updated_at,
      });
    }
    offset += response.data.length;
    if (offset > total || (!response.data.length && offset < total))
      throw new ApiError("CM 分页结果不完整，请重新扫描。", "LIBRARY_CHANGED");
    onProgress({ loaded: records.size, total });
  } while (offset < total);
  return records;
}

export async function readDmbLibrary(
  base,
  { signal, onProgress = () => {} } = {},
) {
  const records = new Map();
  // DMB 的 all 查询只含活动记录，删除和清理记录需显式按状态查询。
  for (const status of [null, "deleted", "purged"]) {
    let offset = 0;
    while (true) {
      signal?.throwIfAborted();
      const { data } = await dmb(base, "/v1/documents/query", {
        method: "POST",
        signal,
        body: {
          ...(status
            ? { mode: "by_status", params: { status } }
            : { mode: "all" }),
          limit: 100,
          offset,
          orderby: "id",
          order: "ASC",
        },
      });
      validateRecords(data, "document_id", "DMB");
      let added = 0;
      for (const document of data) {
        const previous = records.get(document.document_id);
        if (!previous) added++;
        const previousTime = timestampNanos(previous?.updated_at);
        const currentTime = timestampNanos(document.updated_at);
        if (
          !previous ||
          previousTime === null ||
          currentTime === null ||
          currentTime >= previousTime
        )
          records.set(document.document_id, documentSummary(document));
      }
      onProgress({ loaded: records.size, status });
      if (data.length < 100) break;
      if (!added)
        throw new ApiError(
          "DMB 分页未向后推进，请重新扫描。",
          "LIBRARY_CHANGED",
        );
      offset += data.length;
    }
  }
  return records;
}

export async function readLibrariesUntilAnchor(
  base,
  { signal, onProgress = () => {} } = {},
) {
  const controller = new AbortController();
  signal = signal
    ? AbortSignal.any([signal, controller.signal])
    : controller.signal;
  const documents = new Map();
  const comics = new Map();
  let cmTotal = null,
    cmOffset = 0,
    cmMinId = Infinity;
  let offset = 0,
    anchor = null,
    previousTime = null,
    dmbLoaded = 0;
  const cmComplete = () => cmTotal !== null && cmOffset === cmTotal;
  const progress = () =>
    onProgress({ dmbLoaded, cmLoaded: comics.size, cmTotal });
  const readCMPage = async () => {
    if (cmComplete()) return;
    signal?.throwIfAborted();
    const { data, headers } = await api("/comics/query", {
      method: "POST",
      signal,
      body: { order: "DESC", limit: 100, offset: cmOffset },
    });
    signal.throwIfAborted();
    validateRecords(data, "id", "CM");
    const count = headers.get("X-Total-Count");
    if (!/^\d+$/.test(count || "") || !Number.isSafeInteger(Number(count)))
      throw new ApiError(
        "CM 未返回有效总数，无法确认分页范围。",
        "INVALID_RESPONSE",
      );
    if (cmTotal !== null && cmTotal !== Number(count))
      throw new ApiError(
        "CM 库在扫描期间发生了变化，请重新扫描。",
        "LIBRARY_CHANGED",
      );
    cmTotal = Number(count);
    for (const comic of data) {
      if (comic.id >= cmMinId)
        throw new ApiError(
          "CM 排序或分页在扫描期间发生变化，请重新扫描。",
          "LIBRARY_CHANGED",
        );
      cmMinId = comic.id;
      comics.set(comic.id, {
        id: comic.id,
        title: comic.title,
        updated_at: comic.updated_at,
      });
    }
    cmOffset += data.length;
    if (cmOffset > cmTotal || (!data.length && cmOffset < cmTotal))
      throw new ApiError("CM 分页结果不完整，请重新扫描。", "LIBRARY_CHANGED");
    progress();
  };
  const readDMBPage = async () => {
    signal.throwIfAborted();
    const { data } = await dmb(base, "/v1/documents/query", {
      method: "POST",
      signal,
      body: {
        mode: "all",
        limit: 100,
        offset,
        orderby: "updated_at",
        order: "DESC",
      },
    });
    signal?.throwIfAborted();
    validateRecords(data, "document_id", "DMB");
    dmbLoaded += data.length;
    progress();
    return data;
  };
  const result = () => ({
    documents: anchor
      ? new Map(
          [...documents].filter(
            ([, document]) =>
              timestampNanos(document.updated_at) >=
              timestampNanos(anchor.updated_at),
          ),
        )
      : documents,
    comics,
    anchor,
    cmTotal,
    cmMinId,
    cmComplete: cmComplete(),
    dmbLoaded,
  });
  try {
    while (true) {
      // 累积两边各一页后本地匹配；CM 读完后只继续读取 DMB。
      const [, data] = await Promise.all([readCMPage(), readDMBPage()]);
      for (const document of data) {
        const time = timestampNanos(document.updated_at);
        if (time === null)
          throw new ApiError(
            "DMB 更新时间无法比较，请使用全量扫描检查。",
            "INVALID_RESPONSE",
          );
        if (
          (previousTime !== null && time > previousTime) ||
          documents.has(document.document_id)
        )
          throw new ApiError(
            "DMB 排序或分页在扫描期间发生变化，请重新扫描。",
            "LIBRARY_CHANGED",
          );
        previousTime = time;
        documents.set(document.document_id, documentSummary(document));
      }
      // 新 CM 分页也可能匹配较早读到的 DMB 记录，所以每轮按 DMB 顺序重新查找。
      anchor =
        [...documents.values()].find(
          (document) =>
            completionReason(document, comics.get(document.document_id)) ===
            null,
        ) || null;
      // 读完同一更新时间的记录；未覆盖到的 CM ID 保留为尚未核对，不为此预读全库。
      if (
        data.length < 100 ||
        (anchor && previousTime < timestampNanos(anchor.updated_at))
      )
        return result();
      offset += data.length;
    }
  } catch (error) {
    controller.abort();
    throw error;
  }
}

export function oldestFirst(a, b) {
  const left = timestampNanos(a.document?.updated_at);
  const right = timestampNanos(b.document?.updated_at);
  // 活动来源的时间异常必须先处理，不能让它悄悄落在队尾。
  if (left === null || right === null)
    return left === right ? a.id - b.id : left === null ? -1 : 1;
  return left < right ? -1 : left > right ? 1 : a.id - b.id;
}

export function entryQueue(records) {
  // 已删除、已清理和 CM 独有记录只供全量核对，不在 DMB 活动扫描范围内。
  return records
    .filter(
      (row) =>
        row.document && !["deleted", "purged"].includes(row.document.status),
    )
    .sort(oldestFirst);
}

export function entryBlockReason(row) {
  if (!row?.document) return "来源缺失";
  if (["deleted", "purged"].includes(row.document.status))
    return "来源已删除或清理";
  if (timestampNanos(row.document.updated_at) === null)
    return "来源更新时间无法比较，请先修复来源数据";
  if (row.document.source !== "hitomi") return "暂不支持此来源";
  if (!row.document.has_metadata) return "等待来源数据";
  return null;
}

export async function readComic(id, { signal } = {}) {
  signal?.throwIfAborted();
  try {
    const { data } = await api(`/comics/${id}`, { signal });
    signal?.throwIfAborted();
    if (data?.id !== id)
      throw new ApiError("CM 返回了不同的漫画。", "INVALID_RESPONSE");
    return data;
  } catch (error) {
    if (error.status === 404 && error.code === "COMIC_NOT_FOUND") return null;
    throw error;
  }
}

export async function readEntryState(base, id, { signal } = {}) {
  const [comic, source] = await Promise.all([
    readComic(id, { signal }),
    dmb(base, `/v1/documents/${id}`, { signal }),
  ]);
  signal?.throwIfAborted();
  if (source.data?.document_id !== id)
    throw new ApiError(
      "DMB 返回了不同的文档，请重新扫描。",
      "INVALID_RESPONSE",
    );
  return { comic, document: documentSummary(source.data) };
}

export async function readEntryCompletion(base, id, options) {
  // commit 的来源模型可能没有时间；只按 ID 读取持久化结果，与当前 DMB 记录核对。
  const result = await readEntryState(base, id, options);
  if (!result.comic)
    throw new ApiError(
      "漫画已提交，但未能确认 CM 记录，请重试核对。",
      "ENTRY_NOT_CONFIRMED",
    );
  return result;
}

// 每次扫描合并新结果，保留已经在队列中等待处理的记录。
export function retainPendingDocuments(documents, previous, comics) {
  const merged = new Map(documents);
  for (const [id, document] of previous || [])
    if (!merged.has(id) && completionReason(document, comics.get(id)) !== null)
      merged.set(id, document);
  return merged;
}

export function compareLibraries(
  documents,
  comics,
  { full = true, cmMinId = 0 } = {},
) {
  const pending = [];
  let completed = 0;
  // 按 ID 查询得到的 null 表示已确认未入库，Map 中没有键才表示尚未读取。
  const storedIds = [...comics].filter(([, comic]) => comic).map(([id]) => id);
  const ids = new Set([...documents.keys(), ...(full ? storedIds : [])]);
  for (const id of ids) {
    const document = documents.get(id),
      comic = comics.get(id);
    const reason =
      document && !comics.has(id) && id < cmMinId
        ? "unchecked"
        : completionReason(document, comic);
    if (reason === null) completed++;
    else pending.push({ id, document, comic, reason });
  }
  pending.sort(oldestFirst);
  return {
    pending,
    completed,
    dmbTotal: documents.size,
    cmTotal: storedIds.length,
  };
}

export function filterPending(
  records,
  { search = "", reason = "all", status = "all" } = {},
) {
  const needle = search.trim().toLocaleLowerCase();
  return records.filter(
    (row) =>
      (reason === "all" || row.reason === reason) &&
      (status === "all" ||
        (row.document?.status || "missing_source") === status) &&
      (!needle ||
        [
          row.id,
          row.document?.title,
          row.comic?.title,
          row.document?.source,
          row.document?.source_document_id,
        ].some((value) =>
          String(value ?? "")
            .toLocaleLowerCase()
            .includes(needle),
        )),
  );
}
