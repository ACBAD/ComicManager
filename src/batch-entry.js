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

export function batchEntryCandidates(records) {
  return records.filter((row) => !row.comic && row.document);
}

async function enterComic(row, groups) {
  const skipped = (reason) => ({ status: "skipped", reason });
  if (row.comic) return skipped("已经入库");
  if (!row.document) return skipped("来源缺失");
  if (["deleted", "purged"].includes(row.document.status))
    return skipped("来源已删除或清理");
  if (row.document.source !== "hitomi") return skipped("暂不支持此来源");
  if (!row.document.has_metadata) return skipped("缺少来源数据");

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
  if (other.length) return skipped(`${other.length} 个非 group 类标签未映射`);
  if (missing.some((tag) => !tag.origin_name.trim()))
    return skipped("group 标签缺少名称");

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
  // 只新增，其他会话已经录入时由服务端拒绝覆盖。
  await api(`/comics/${row.id}/commit`, { method: "POST" });
  return {
    status: "success",
    reason: missing.length
      ? `补齐 ${missing.length} 条 group 映射后录入，新建 ${created} 个通用标签`
      : "全部标签已映射，直接录入",
  };
}

export async function runBatchEntry(
  records,
  {
    groups,
    shouldStop = () => false,
    onCurrent = () => {},
    onResult = () => {},
  },
) {
  let processed = 0;
  for (const row of records) {
    if (shouldStop()) return { stopped: true, processed };
    onCurrent(row);
    let result;
    let fatal = false;
    try {
      result = await enterComic(row, groups);
    } catch (error) {
      const skip = {
        COMIC_ALREADY_EXISTS: "已被其他操作录入，未覆盖",
        UNMAPPED_SPECIFIC_TAGS: "映射已变化，本次跳过",
        SOURCE_DOCUMENT_NOT_FOUND: "来源已不存在",
        SPECIFIC_TAG_MAPPING_CONFLICT: "标签映射冲突，未提交",
      }[error.code];
      result = {
        status: skip ? "skipped" : "failed",
        reason: skip || error.message,
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
  }
  return { stopped: false, processed };
}
