import {
  ApiError,
  api,
  query,
  stableKey,
  genericKey,
  inferGroup,
  mapLimit,
  exactMapping,
  ensureGeneric,
} from "./entry-api.js";
import {
  entryQueue,
  entryBlockReason,
  completionReason,
  readEntryCompletion,
} from "./pending-comics.js?v=anchor-batches-1";

async function enterComic(row, groups, base) {
  const blocked = (reason) => ({ status: "blocked", reason });
  const unavailable = entryBlockReason(row);
  if (unavailable) return blocked(unavailable);

  const { data: preview } = await api(`/comics/${row.id}/preview`);
  const tags = [
    ...new Map(preview.comic_tags.map((tag) => [stableKey(tag), tag])).values(),
  ];
  // 等待整部的精确查询完成再决定是否写入，不使用同名候选或手动分类。
  const mappings = await mapLimit(tags, 6, async (tag) => {
    try {
      return { tag, mapping: await exactMapping(tag) };
    } catch (error) {
      return { tag, error };
    }
  });
  const error = mappings.find((item) => item.error)?.error;
  if (error) throw error;
  const missing = mappings
    .filter((item) => !item.mapping)
    .map((item) => item.tag);
  const other = missing.filter((tag) => inferGroup(tag, groups) !== "group");
  if (other.length) return blocked(`${other.length} 个非 group 类标签未映射`);
  if (missing.some((tag) => !tag.origin_name.trim()))
    return blocked("group 标签缺少名称");

  let created = 0;
  for (const tag of missing) {
    const target = { tag_group: "group", name: tag.origin_name.trim() };
    const generic = await ensureGeneric(target);
    if (generic.created) created++;
    await query("/tags/specific", {
      specific_tag: tag,
      generic_tag_id: generic.id,
    });
    const actual = await exactMapping(tag);
    if (!actual || genericKey(actual.generic) !== genericKey(target))
      throw new ApiError(
        "group 映射未能确认，漫画未提交。",
        "SPECIFIC_TAG_MAPPING_CONFLICT",
      );
  }
  const { data } = await api(
    `/comics/${row.id}/commit${row.comic ? "?allow_override=true" : ""}`,
    { method: "POST" },
  );
  const persisted = await readEntryCompletion(base, row.id, data.title);
  if (completionReason(persisted.document, persisted.comic) !== null)
    return {
      ...blocked("已提交，但 CM 更新时间尚未晚于 DMB，当前部仍留在队列"),
      ...persisted,
    };
  return {
    status: "success",
    ...persisted,
    reason: missing.length
      ? `补齐 ${missing.length} 条 group 映射后录入，新建 ${created} 个通用标签`
      : "全部标签已映射，直接录入",
  };
}

export async function runBatchEntry(
  records,
  {
    groups,
    dmbUrl,
    shouldStop = () => false,
    onCurrent = () => {},
    onResult = () => {},
  },
) {
  let processed = 0;
  for (const row of entryQueue(records)) {
    if (shouldStop()) return { stopped: true, processed };
    onCurrent(row);
    let result;
    let fatal = false;
    try {
      result = await enterComic(row, groups, dmbUrl);
    } catch (error) {
      const blockedReason = {
        COMIC_ALREADY_EXISTS: "已被其他操作录入，未覆盖",
        UNMAPPED_SPECIFIC_TAGS: "映射已变化，需要手动处理当前部",
        SOURCE_DOCUMENT_NOT_FOUND: "来源已不存在",
        SPECIFIC_TAG_MAPPING_CONFLICT: "标签映射冲突，未提交",
      }[error.code];
      result = {
        status: blockedReason ? "blocked" : "failed",
        reason: blockedReason || error.message,
      };
      fatal = [401, 403].includes(error.status);
    }
    processed++;
    onResult({
      id: row.id,
      title: row.document?.title || row.comic?.title || `漫画 #${row.id}`,
      ...result,
    });
    if (fatal)
      return {
        stopped: true,
        processed,
        reason: "身份验证或权限不足，已停止批量录入。",
      };
    if (result.status !== "success")
      return {
        stopped: true,
        processed,
        reason: `已停在 #${row.id}：${result.reason}。处理完成后再继续。`,
      };
  }
  return { stopped: false, processed };
}
