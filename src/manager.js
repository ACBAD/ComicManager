import {
  DEFAULT_DMB_URL,
  GROUP_NAMES,
  ApiError,
  api,
  query,
  dmb,
  validateDmbUrl,
  sourceLink,
  stableKey,
  genericKey,
  inferGroup,
  mapLimit,
  exactGeneric,
  ensureGeneric,
  exactMapping,
  similarCandidates,
} from "./entry-api.js";

const $ = (id) => document.getElementById(id);
const groupLabel = (group) => `${GROUP_NAMES[group] || group} · ${group}`;
const statusLabels = {
  loading: "查询中",
  resolved: "已映射",
  recommended: "有推荐",
  unresolved: "待处理",
  saving: "保存中",
  error: "请求失败",
};
const state = {
  view: "home",
  phase: "idle",
  hash: null,
  groups: [],
  preview: null,
  source: null,
  sourceError: null,
  revision: null,
  items: [],
  active: null,
  pendingWrites: 0,
  createdGeneric: new Set(),
  createdSpecific: new Set(),
  message: null,
  queueSearch: "",
  queueStatus: "all",
  queueGroup: "all",
  archiveOffset: 0,
};
let dmbUrl = DEFAULT_DMB_URL;
try {
  dmbUrl = validateDmbUrl(
    localStorage.getItem("comicmanager.dmbUrl") || DEFAULT_DMB_URL,
  );
} catch {
  /* 使用默认地址 */
}
let pageController = new AbortController();
let searchController;
let searchTimer;
let libraryController;
let libraryDetailController;
let routeVersion = 0;
let archiveVersion = 0;
let activeSearchVersion = 0;

// 所有来源名称与 metadata 都作为文本节点输出。
function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key.startsWith("on"))
      node.addEventListener(key.slice(2).toLowerCase(), value);
    else if (key === "class") node.className = value;
    else if (key === "value") node.value = value;
    else if (
      ["disabled", "checked", "selected", "hidden", "open"].includes(key)
    )
      node[key] = !!value;
    else if (value !== null && value !== undefined)
      node.setAttribute(key, value);
  }
  for (const child of [children].flat(Infinity)) {
    if (child !== null && child !== undefined)
      node.append(
        child instanceof Node ? child : document.createTextNode(String(child)),
      );
  }
  return node;
}
function button(
  text,
  action,
  className = "btn btn-outline-secondary",
  attrs = {},
) {
  return el(
    "button",
    { type: "button", class: className, onclick: action, ...attrs },
    text,
  );
}
function rawDetails(title, data, open = false) {
  return el("details", { class: "raw-details", open }, [
    el("summary", {}, title),
    el("pre", {}, JSON.stringify(data, null, 2)),
  ]);
}
function setService(connected) {
  $("service-state").className =
    `service-label ${connected ? "connected" : "failed"}`;
  $("service-state").replaceChildren(
    el("span", { class: "status-dot" }),
    document.createTextNode(connected ? "DMB 已连接" : "DMB 未连接"),
  );
}
function announce(text) {
  $("announcer").textContent = text;
}
function message(text, type = "warning", error = null, retry = null) {
  state.message = { text, type, error, retry };
  renderMessage();
}
function errorBox(error, retry, text = error.message) {
  const body = el("div", { class: "message-body" }, el("p", {}, text));
  if (error.status === 401 || error.code === "AUTHENTICATION_REQUIRED") {
    body.append(
      el("a", { href: "/auth", class: "d-block mt-2" }, "前往身份验证"),
    );
  }
  if (error.code === "META_SCHEMA_VIOLATION")
    body.append(
      el(
        "p",
        { class: "mt-2" },
        "来源标签结构与数据库不一致，请联系维护者处理。",
      ),
    );
  if (error.code || Object.keys(error.details || {}).length)
    body.append(rawDetails("错误详情", { code: error.code, ...error.details }));
  return el("div", { class: "alert alert-danger", role: "alert" }, [
    body,
    retry && error.code !== "META_SCHEMA_VIOLATION"
      ? button("重试", retry, "btn btn-sm btn-outline-secondary")
      : null,
  ]);
}
function renderMessage() {
  const box = $("global-message");
  box.replaceChildren();
  if (!state.message) return;
  const { text, type, error, retry } = state.message;
  const node = error
    ? errorBox(error, retry, text)
    : el(
        "div",
        { class: `alert alert-${type}` },
        el("div", { class: "message-body" }, text),
      );
  node.append(
    button(
      "×",
      () => {
        state.message = null;
        renderMessage();
      },
      "btn btn-sm btn-quiet",
      { "aria-label": "关闭提示" },
    ),
  );
  box.append(node);
}
function options(select, selected = "", placeholder = false) {
  select.replaceChildren(
    ...(placeholder ? [el("option", { value: "" }, "请选择分类")] : []),
    ...state.groups.map((group) =>
      el("option", { value: group }, groupLabel(group)),
    ),
  );
  select.value = selected;
}
async function loadGroups(signal) {
  if (!state.groups.length)
    state.groups = (await api("/tags/groups", { signal })).data;
}
const unresolved = () =>
  state.items.filter((item) => item.status !== "resolved");
const dirty = () => state.items.some((item) => item.dirty);
const canCommit = () =>
  !!state.preview &&
  unresolved().length === 0 &&
  state.pendingWrites === 0 &&
  ["resolving", "review"].includes(state.phase);

function showPage(view) {
  state.view = view;
  for (const name of ["home", "entry", "loading", "tags"])
    $(name + "-page").hidden = name !== view;
  $("nav-tags").toggleAttribute("aria-current", view === "tags");
  $("nav-entry").toggleAttribute("aria-current", view !== "tags");
  if (view === "tags") $("nav-tags").setAttribute("aria-current", "page");
  else $("nav-entry").setAttribute("aria-current", "page");
}

async function route() {
  const hash = location.hash || "#/";
  if (state.hash !== null && hash !== state.hash) {
    if (state.pendingWrites || state.phase === "committing") {
      history.replaceState(null, "", state.hash);
      message("正在保存，请等待操作完成。");
      return;
    }
    if (
      dirty() &&
      !confirm("当前尚未保存的标签选择将被清除，是否离开？已保存的映射会保留。")
    ) {
      history.replaceState(null, "", state.hash);
      return;
    }
  }
  state.hash = hash;
  pageController.abort();
  pageController = new AbortController();
  searchController?.abort();
  libraryController?.abort();
  libraryDetailController?.abort();
  clearTimeout(searchTimer);
  const version = ++routeVersion;
  state.message = null;
  state.items = [];
  state.preview = null;
  state.phase = "idle";
  renderMessage();
  const match = hash.match(/^#\/entry\/(\d+)$/);
  if (match && Number.isSafeInteger(Number(match[1]))) {
    await loadEntry(Number(match[1]), version);
  } else if (hash === "#/tags") {
    document.title = "标签管理 · ComicManager";
    showPage("tags");
    try {
      await loadGroups(pageController.signal);
      if (version !== routeVersion) return;
      options($("library-group"), state.groups[0]);
      await loadLibrary();
    } catch (error) {
      if (version === routeVersion)
        message(error.message, "danger", error, route);
    }
  } else {
    document.title = "漫画录入 · ComicManager";
    showPage("home");
    await loadArchives();
  }
}

async function loadArchives(offset = state.archiveOffset) {
  const version = ++archiveVersion;
  state.archiveOffset = offset;
  $("archive-list").replaceChildren(
    el("p", { class: "text-secondary py-4" }, "正在读取最近归档…"),
  );
  $("archive-pagination").replaceChildren();
  try {
    const { data } = await dmb(dmbUrl, "/v1/documents/query", {
      method: "POST",
      body: {
        mode: "by_status",
        params: { status: "archived" },
        limit: 6,
        offset,
        orderby: "id",
        order: "DESC",
      },
    });
    if (version !== archiveVersion) return;
    setService(true);
    if (!data?.length) {
      $("archive-list").replaceChildren(
        empty("还没有可显示的归档", "可以直接输入文档 ID 进入录入。"),
      );
    } else {
      $("archive-list").replaceChildren(
        ...data.map((doc) =>
          el("div", { class: "archive-row" }, [
            el("span", { class: "archive-number" }, `#${doc.document_id}`),
            el("div", { class: "archive-title" }, [
              el("strong", {}, doc.title || "未命名归档"),
              el(
                "small",
                {},
                `${doc.source} · 来源 #${doc.source_document_id} · ${doc.progress?.total || doc.pages?.length || 0} 页`,
              ),
            ]),
            el("span", { class: "archive-status" }, "已归档"),
            el(
              "a",
              {
                class: "btn btn-sm btn-outline-secondary",
                href: `#/entry/${doc.document_id}`,
              },
              "整理标签 →",
            ),
          ]),
        ),
      );
    }
    $("archive-pagination").replaceChildren(
      button(
        "上一页",
        () => loadArchives(Math.max(0, offset - 6)),
        "btn btn-sm btn-quiet",
        { disabled: offset === 0 },
      ),
      el("span", {}, `第 ${offset / 6 + 1} 页`),
      button("下一页", () => loadArchives(offset + 6), "btn btn-sm btn-quiet", {
        disabled: (data?.length || 0) < 6,
      }),
    );
  } catch (error) {
    if (version !== archiveVersion) return;
    setService(false);
    $("archive-list").replaceChildren(
      errorBox(
        error,
        () => loadArchives(offset),
        "暂时无法读取归档列表。可检查连接设置，或输入文档 ID 重试。",
      ),
    );
  }
}
function empty(title, subtitle = "") {
  return el("div", { class: "empty-state" }, [
    el("span", { class: "empty-symbol", "aria-hidden": "true" }, "⌁"),
    el("strong", {}, title),
    el("p", {}, subtitle),
  ]);
}

async function loadEntry(
  id,
  version = ++routeVersion,
  notice = null,
  preserveCreated = false,
) {
  state.phase = "loading";
  state.comicId = id;
  state.items = [];
  state.source = null;
  state.sourceError = null;
  state.active = null;
  if (!preserveCreated) {
    state.createdGeneric = new Set();
    state.createdSpecific = new Set();
  }
  showPage("loading");
  const signal = pageController.signal;
  try {
    // 来源详情与 Comic 是独立资源；来源服务暂不可读时仍保留 Comic 预览。
    const sourceResult = dmb(dmbUrl, `/v1/documents/${id}`, { signal }).then(
      (r) => ({ data: r.data }),
      (error) => ({ error }),
    );
    const [preview, , source] = await Promise.all([
      api(`/comics/${id}/preview`, { signal }),
      loadGroups(signal),
      sourceResult,
    ]);
    if (version !== routeVersion) return;
    const revision = preview.headers.get("ETag")?.replace(/^"|"$/g, "");
    if (!/^sha256:[0-9a-f]{64}$/.test(revision || ""))
      throw new ApiError(
        "预览缺少有效的来源版本，无法提交。",
        "MISSING_SOURCE_REVISION",
      );
    state.preview = preview.data;
    state.revision = revision;
    state.source = source.data || null;
    state.sourceError = source.error || null;
    setService(!source.error);
    state.items = [
      ...new Map(
        preview.data.comic_tags.map((tag) => [stableKey(tag), tag]),
      ).entries(),
    ].map(([key, tag]) => ({
      key,
      tag,
      status: "loading",
      mapping: null,
      candidates: [],
      selected: null,
      group: inferGroup(tag, state.groups),
      mode: "recommend",
      name: tag.origin_name,
      searchText: tag.origin_name,
      searchResults: [],
      searchTotal: 0,
      searchOffset: 0,
      searchLoading: false,
      error: null,
      conflict: null,
      dirty: false,
    }));
    state.active = state.items[0]?.key ?? null;
    state.phase = "resolving";
    state.queueSearch = "";
    state.queueStatus = "all";
    state.queueGroup = "all";
    $("queue-search").value = "";
    $("queue-status").value = "all";
    $("queue-group").replaceChildren(
      el("option", { value: "all" }, "全部分组"),
      ...[
        ...new Set(state.items.map((item) => item.tag.group || "无来源分组")),
      ].map((group) => el("option", { value: group }, group)),
    );
    showPage("entry");
    document.title = `${state.preview.title} · 漫画录入`;
    if (notice) message(notice, "warning");
    else if (source.error)
      message(
        "来源详情暂时无法读取；漫画预览已加载。可以重试读取来源数据。",
        "warning",
        source.error,
        refreshSource,
      );
    renderEntry();
    await mapLimit(state.items, 6, (item) =>
      resolveItem(item, version, signal),
    );
    if (version === routeVersion) {
      activate(unresolved()[0]?.key ?? state.items[0]?.key ?? null);
      announce(`标签查询完成，${unresolved().length} 个待处理。`);
    }
  } catch (error) {
    if (version !== routeVersion || signal.aborted) return;
    state.phase = "fatal-error";
    showPage("home");
    $("comic-id").value = id;
    message(error.message, "danger", error, () => loadEntry(id));
  }
}

async function refreshSource() {
  const version = routeVersion;
  try {
    const { data } = await dmb(dmbUrl, `/v1/documents/${state.comicId}`, {
      signal: pageController.signal,
    });
    if (version !== routeVersion) return;
    state.source = data;
    state.sourceError = null;
    state.message = null;
    setService(true);
    renderMessage();
    renderSummary();
  } catch (error) {
    if (version === routeVersion)
      message(error.message, "danger", error, refreshSource);
  }
}

async function resolveItem(
  item,
  version = routeVersion,
  signal = pageController.signal,
) {
  item.status = "loading";
  item.error = null;
  item.conflict = null;
  if (version === routeVersion) renderEntry(false);
  try {
    const mapping = await exactMapping(item.tag, signal);
    if (version !== routeVersion) return;
    if (mapping) {
      item.mapping = mapping;
      item.status = "resolved";
      item.dirty = false;
    } else {
      item.mapping = null;
      item.status = "unresolved";
    }
  } catch (error) {
    if (version !== routeVersion || signal.aborted) return;
    item.status = "error";
    item.error = error;
  }
  if (version === routeVersion) {
    renderEntry(state.active === item.key);
    if (state.active === item.key && item.status === "unresolved")
      await loadCandidates(item, version);
  }
}

async function loadCandidates(item, version = routeVersion) {
  if (
    item.candidatesLoaded ||
    item.candidatesLoading ||
    item.status === "resolved"
  )
    return;
  item.candidatesLoading = true;
  renderEntry();
  try {
    const candidates = await similarCandidates(item.tag, pageController.signal);
    if (
      item.group === "group" &&
      !candidates.some(
        (candidate) =>
          candidate.generic.tag_group === "group" &&
          candidate.generic.name === item.tag.origin_name,
      )
    ) {
      const generic = { tag_group: "group", name: item.tag.origin_name };
      const id = await exactGeneric(generic, pageController.signal);
      if (id !== null) candidates.push({ generic, evidence: [] });
    }
    if (version !== routeVersion) return;
    item.candidates = candidates;
    item.candidatesLoaded = true;
    item.status = candidates.length ? "recommended" : "unresolved";
    if (!item.dirty) {
      item.mode = candidates.length ? "recommend" : "create";
      item.selected = candidates.length === 1 ? candidates[0].generic : null;
      if (item.selected) item.group = item.selected.tag_group;
    }
  } catch (error) {
    if (version !== routeVersion || pageController.signal.aborted) return;
    item.status = "error";
    item.error = error;
  } finally {
    item.candidatesLoading = false;
    if (version === routeVersion) renderEntry(state.active === item.key);
  }
}

async function activate(key, focusEditor = false) {
  if (state.pendingWrites) return;
  searchController?.abort();
  clearTimeout(searchTimer);
  ++activeSearchVersion;
  state.active = key;
  const item = state.items.find((item) => item.key === key);
  renderEntry();
  if (item && ["unresolved", "recommended"].includes(item.status))
    await loadCandidates(item);
  window.bootstrap?.Offcanvas.getInstance($("tag-queue"))?.hide();
  if (focusEditor && state.active === key) {
    document
      .querySelector(
        "#tag-editor select:not(:disabled), #tag-editor button:not(:disabled)",
      )
      ?.focus();
  }
}
function nextItem() {
  const index = state.items.findIndex((item) => item.key === state.active);
  const ordered = [
    ...state.items.slice(index + 1),
    ...state.items.slice(0, index + 1),
  ];
  const next = ordered.find((item) => item.status !== "resolved");
  if (next) void activate(next.key, true);
  else {
    state.phase = "review";
    renderEntry();
    announce("全部标签已映射，请复核录入。");
  }
}

function renderSummary() {
  const comic = state.preview;
  if (!comic) return;
  const done = state.items.length - unresolved().length;
  const percent = state.items.length ? (done / state.items.length) * 100 : 100;
  const source = state.source;
  $("comic-summary").replaceChildren(
    el("div", {}, [
      el("div", { class: "source-label" }, [
        el(
          "span",
          { class: "source-badge" },
          source?.source || comic.comic_tags[0]?.site || "归档",
        ),
        el("span", {}, `DMB #${comic.id}`),
        source ? el("span", {}, `来源 #${source.source_document_id}`) : null,
      ]),
      el("h1", {}, comic.title),
      el("div", { class: "summary-meta" }, [
        el("span", {}, comic.authors.join(" / ") || "作者未提供"),
        el("span", {}, `${comic.comic_tags.length} 个来源标签`),
        comic.series_name ? el("span", {}, comic.series_name) : null,
      ]),
    ]),
    el("div", { class: "summary-progress" }, [
      el("span", { class: "progress-number" }, [
        done,
        el("small", {}, ` / ${state.items.length}`),
      ]),
      el("span", { class: "progress-caption" }, "标签映射完成"),
      el(
        "div",
        {
          class: "progress",
          role: "progressbar",
          "aria-label": "标签映射进度",
          "aria-valuemin": "0",
          "aria-valuemax": String(state.items.length || 1),
          "aria-valuenow": String(state.items.length ? done : 1),
        },
        el("div", { class: "progress-bar", style: `width:${percent}%` }),
      ),
    ]),
  );
}
function renderQueue() {
  $("queue-count").textContent = `${state.items.length} 项`;
  const scrollTop = $("queue-list").scrollTop;
  const visible = state.items.filter((item) => {
    const nameMatch = item.tag.origin_name
      .toLowerCase()
      .includes(state.queueSearch.toLowerCase());
    const statusMatch =
      state.queueStatus === "all" ||
      (state.queueStatus === "pending"
        ? item.status !== "resolved"
        : item.status === state.queueStatus);
    return (
      nameMatch &&
      statusMatch &&
      (state.queueGroup === "all" ||
        (item.tag.group || "无来源分组") === state.queueGroup)
    );
  });
  $("queue-list").replaceChildren(
    ...visible
      .map((item) =>
        button("", () => activate(item.key), "queue-item", {
          "aria-current": String(state.active === item.key),
          disabled: state.pendingWrites > 0,
        }),
      )
      .map((node, index) => {
        const item = visible[index];
        node.append(
          el(
            "span",
            { class: `queue-symbol ${item.status}`, "aria-hidden": "true" },
            item.status === "resolved"
              ? "✓"
              : item.status === "error"
                ? "!"
                : "○",
          ),
          el("span", { class: "queue-item-main" }, [
            el("strong", {}, item.tag.origin_name),
            el(
              "small",
              {},
              [item.tag.group || item.tag.site, item.tag.tag_sex]
                .filter(Boolean)
                .join(" · "),
            ),
          ]),
          el(
            "span",
            { class: `queue-state ${item.status}` },
            statusLabels[item.status],
          ),
        );
        return node;
      }),
  );
  if (!visible.length)
    $("queue-list").append(
      el(
        "p",
        { class: "text-secondary p-4 small" },
        "没有符合筛选条件的标签。",
      ),
    );
  $("queue-list").scrollTop = scrollTop;
}
function metadataFields(tag) {
  const names = {
    site: "来源站点",
    group: "原始分组",
    tag_sex: "性别",
    url: "来源链接",
  };
  const entries = Object.entries(tag).filter(([key]) => key !== "origin_name");
  return el(
    "dl",
    { class: "metadata-grid" },
    entries.map(([key, value]) => {
      const href = key === "url" ? sourceLink(value, tag.site) : null;
      return el("div", {}, [
        el("dt", {}, names[key] || key),
        el(
          "dd",
          {},
          href
            ? el(
                "a",
                { href, target: "_blank", rel: "noopener noreferrer" },
                value,
              )
            : value === null
              ? "—"
              : typeof value === "object"
                ? JSON.stringify(value)
                : value,
        ),
      ]);
    }),
  );
}

function renderEditor() {
  const node = $("tag-editor");
  const item = state.items.find((item) => item.key === state.active);
  const active = document.activeElement;
  const focusId = node.contains(active) ? active.id : null;
  const selection =
    active?.selectionStart === undefined
      ? null
      : [active.selectionStart, active.selectionEnd];
  node.replaceChildren();
  if (!item) {
    node.append(empty("这部漫画没有需要整理的标签", "可直接进入最终复核。"));
    return;
  }
  node.append(
    el("div", { class: "editor-eyebrow" }, [
      el("span", {}, "来源标签 / SPECIFIC TAG"),
      el(
        "span",
        {},
        `${state.items.indexOf(item) + 1} / ${state.items.length}`,
      ),
    ]),
    el("h2", { class: "tag-title" }, item.tag.origin_name),
    metadataFields(item.tag),
    rawDetails("查看完整标签数据", item.tag),
  );
  if (item.status === "loading") {
    node.append(el("div", { class: "blank-editor" }, "正在查询精确映射…"));
  } else if (item.status === "resolved") {
    node.append(
      el("div", { class: "resolved-box" }, [
        el("span", {}, "✓ 已映射到通用标签"),
        el("h3", {}, item.mapping.generic.name),
        el("p", {}, groupLabel(item.mapping.generic.tag_group)),
      ]),
      el("div", { class: "editor-actions" }, [
        el("small", {}, "此映射已保存，刷新页面后仍会保留。"),
        button(
          unresolved().length ? "处理下一项 →" : "查看最终复核 →",
          nextItem,
          "btn btn-primary",
        ),
      ]),
    );
  } else if (item.status === "error") {
    node.append(
      errorBox(item.error, () => {
        item.candidatesLoaded = false;
        void resolveItem(item);
      }),
    );
    if (item.conflict) {
      node.append(
        el(
          "p",
          { class: "small" },
          `你选择了「${groupLabel(item.conflict.wanted.tag_group)} / ${item.conflict.wanted.name}」，现有映射为「${groupLabel(item.conflict.actual.generic.tag_group)} / ${item.conflict.actual.generic.name}」。`,
        ),
        button(
          "接受现有映射并继续",
          () => {
            item.mapping = item.conflict.actual;
            item.conflict = null;
            item.error = null;
            item.dirty = false;
            item.status = "resolved";
            nextItem();
          },
          "btn btn-outline-primary",
        ),
      );
    }
  } else {
    renderDecision(node, item);
  }
  if (focusId && $(focusId)) {
    $(focusId).focus({ preventScroll: true });
    if (selection && ["text", "search"].includes($(focusId).type))
      $(focusId).setSelectionRange(...selection);
  }
}

function renderDecision(node, item) {
  const busy = state.pendingWrites > 0 || item.candidatesLoading;
  const area = el("div", { class: "decision-area" });
  const select = el("select", {
    id: "mapping-group",
    class: "form-select",
    disabled: busy,
    onchange: (event) => {
      item.group = event.target.value;
      item.selected = null;
      item.dirty = true;
      if (item.mode === "search") void searchGeneric(item);
      renderEditor();
    },
  });
  options(select, item.group, true);
  area.append(
    el("div", { class: "group-line" }, [
      el("label", { for: "mapping-group" }, "标签分类"),
      select,
      el(
        "small",
        {},
        item.group ? "按语义选择通用分类" : "请根据来源信息选择分类",
      ),
    ]),
  );
  area.append(
    el(
      "div",
      { class: "mode-tabs", role: "tablist", "aria-label": "映射方式" },
      [
        ["recommend", "推荐候选"],
        ["search", "搜索已有标签"],
        ["create", "创建新标签"],
      ].map(([mode, name]) =>
        button(
          name,
          () => {
            item.mode = mode;
            item.selected =
              mode === "recommend" && item.candidates.length === 1
                ? item.candidates[0].generic
                : null;
            if (item.selected) item.group = item.selected.tag_group;
            renderEditor();
            if (mode === "search") void searchGeneric(item);
          },
          "mode-tab",
          {
            role: "tab",
            "aria-selected": String(item.mode === mode),
            disabled: busy,
          },
        ),
      ),
    ),
  );
  if (item.candidatesLoading)
    area.append(
      el("p", { class: "mode-description" }, "正在读取同原名标签的候选映射…"),
    );
  else if (item.mode === "recommend") {
    area.append(
      el(
        "p",
        { class: "mode-description" },
        "相同来源与原名的标签提供以下候选，请确认后采用。",
      ),
    );
    if (!item.candidates.length)
      area.append(
        empty("暂无同原名候选", "可以搜索已有标签，或创建新的通用标签。"),
      );
    else
      area.append(
        ...item.candidates.map((candidate) =>
          candidateNode(candidate, item, busy),
        ),
      );
  } else if (item.mode === "search") {
    const input = el("input", {
      id: "mapping-search",
      type: "search",
      class: "form-control",
      placeholder: "在当前分类中搜索",
      value: item.searchText,
      disabled: busy || !item.group,
      oninput: (event) => {
        item.searchText = event.target.value;
        item.selected = null;
        searchController?.abort();
        ++activeSearchVersion;
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => searchGeneric(item), 300);
        updateSaveButton(item);
      },
    });
    area.append(
      el("div", { class: "mapping-form" }, [
        el(
          "label",
          { for: "mapping-search", class: "form-label" },
          "通用标签名称",
        ),
        input,
        el(
          "p",
          { class: "form-text" },
          item.group
            ? `搜索范围：${groupLabel(item.group)}`
            : "先选择标签分类，再搜索已有标签。",
        ),
      ]),
    );
    if (item.searchLoading)
      area.append(el("p", { class: "mode-description" }, "正在搜索…"));
    else if (item.searchError)
      area.append(errorBox(item.searchError, () => searchGeneric(item)));
    else if (item.group && !item.searchResults.length)
      area.append(
        empty("没有匹配的通用标签", "换个名称搜索，或切换到创建新标签。"),
      );
    else
      area.append(
        ...item.searchResults.map((generic) =>
          candidateNode({ generic, evidence: [] }, item, busy),
        ),
      );
    if (item.searchTotal > 10)
      area.append(
        el("div", { class: "pagination-bar" }, [
          button(
            "上一页",
            () => searchGeneric(item, item.searchOffset - 10),
            "btn btn-sm btn-quiet",
            { disabled: item.searchOffset === 0 || item.searchLoading },
          ),
          el("span", {}, `共 ${item.searchTotal} 项`),
          button(
            "下一页",
            () => searchGeneric(item, item.searchOffset + 10),
            "btn btn-sm btn-quiet",
            {
              disabled:
                item.searchOffset + 10 >= item.searchTotal ||
                item.searchLoading,
            },
          ),
        ]),
      );
  } else {
    area.append(
      el("div", { class: "mapping-form" }, [
        el(
          "label",
          { for: "mapping-name", class: "form-label" },
          "新通用标签名称",
        ),
        el("input", {
          id: "mapping-name",
          class: "form-control",
          type: "text",
          value: item.name,
          disabled: busy,
          autocomplete: "off",
          "aria-describedby": "mapping-name-hint",
          oninput: (event) => {
            item.name = event.target.value;
            item.dirty = true;
            updateSaveButton(item);
          },
        }),
        el(
          "p",
          { id: "mapping-name-hint", class: "form-text" },
          item.group === "group"
            ? "社团名称优先保留原名。存在同组同名标签时会直接复用。"
            : "创建通用标签后立即建立当前来源标签的映射。存在同组同名标签时直接复用。",
        ),
      ]),
    );
  }
  area.append(
    el("div", { class: "editor-actions" }, [
      el("small", {}, "映射保存后自动进入下一项"),
      button(
        item.status === "saving"
          ? "正在保存…"
          : item.mode === "create"
            ? "创建并映射，下一项 →"
            : "采用并处理下一项 →",
        () => saveMapping(item),
        "btn btn-primary",
        { id: "save-mapping", disabled: !saveAllowed(item) },
      ),
    ]),
  );
  node.append(area);
}
function saveAllowed(item) {
  return (
    !state.pendingWrites &&
    !item.candidatesLoading &&
    ["unresolved", "recommended"].includes(item.status) &&
    (item.mode === "create"
      ? state.groups.includes(item.group) && !!item.name.trim()
      : !!item.selected)
  );
}
function updateSaveButton(item) {
  if ($("save-mapping")) $("save-mapping").disabled = !saveAllowed(item);
}
function candidateNode(candidate, item, disabled) {
  const { generic, evidence } = candidate;
  const selected =
    item.selected && genericKey(item.selected) === genericKey(generic);
  const radio = el("input", {
    type: "radio",
    name: "mapping-candidate",
    checked: selected,
    disabled,
    onchange: () => {
      item.selected = generic;
      item.group = generic.tag_group;
      item.dirty = true;
      renderEditor();
    },
  });
  const node = el(
    "div",
    { class: `candidate${selected ? " selected" : ""}` },
    el("label", { class: "candidate-choice" }, [
      radio,
      el("div", {}, [
        el("div", { class: "candidate-name" }, generic.name),
        el("div", { class: "candidate-group" }, groupLabel(generic.tag_group)),
      ]),
      el(
        "span",
        { class: "candidate-evidence" },
        evidence.length ? `${evidence.length} 条来源证据` : "已有通用标签",
      ),
    ]),
  );
  if (evidence.length)
    node.append(
      el("details", {}, [
        el("summary", {}, "展开来源证据"),
        ...evidence.map((tag) =>
          el("div", { class: "evidence-row" }, [
            el(
              "span",
              {},
              `${tag.site} · ${tag.group || "无来源分组"} · ${tag.tag_sex || "未区分性别"}`,
            ),
            sourceLink(tag.url, tag.site)
              ? el(
                  "a",
                  {
                    href: sourceLink(tag.url, tag.site),
                    target: "_blank",
                    rel: "noopener noreferrer",
                  },
                  tag.url,
                )
              : null,
          ]),
        ),
      ]),
    );
  return node;
}

async function searchGeneric(item, offset = 0) {
  searchController?.abort();
  const controller = (searchController = new AbortController());
  const searchVersion = ++activeSearchVersion;
  const version = routeVersion;
  if (!item.group) {
    item.searchResults = [];
    item.searchTotal = 0;
    item.searchLoading = false;
    renderEditor();
    return;
  }
  const group = item.group,
    name = item.searchText;
  item.searchLoading = true;
  item.searchError = null;
  item.searchOffset = offset;
  item.selected = null;
  renderEditor();
  try {
    const response = await query(
      "/tags/generic/query",
      { tag_group: group, name, name_match: "contains", limit: 10, offset },
      controller.signal,
    );
    const results = await mapLimit(
      response.data,
      6,
      async (id) =>
        (await api(`/tags/generic/${id}`, { signal: controller.signal })).data,
    );
    if (version !== routeVersion || searchVersion !== activeSearchVersion)
      return;
    item.searchResults = results;
    item.searchTotal = Number(response.headers.get("X-Total-Count"));
  } catch (error) {
    if (
      !controller.signal.aborted &&
      version === routeVersion &&
      searchVersion === activeSearchVersion
    )
      item.searchError = error;
  } finally {
    if (version === routeVersion && searchVersion === activeSearchVersion) {
      item.searchLoading = false;
      if (state.active === item.key && item.mode === "search") renderEditor();
    }
  }
}

async function saveMapping(item) {
  if (!saveAllowed(item)) return;
  const target =
    item.mode === "create"
      ? { tag_group: item.group, name: item.name.trim() }
      : item.selected;
  state.pendingWrites++;
  item.status = "saving";
  item.error = null;
  renderEntry();
  let saved = false;
  try {
    let id;
    if (item.mode === "create") {
      const generic = await ensureGeneric(target);
      id = generic.id;
      if (generic.created) state.createdGeneric.add(genericKey(target));
    } else {
      id = await exactGeneric(target);
      if (id === null)
        throw new ApiError(
          "选中的通用标签已不存在，请重新查询。",
          "GENERIC_TAG_NOT_FOUND",
        );
    }
    try {
      const response = await query("/tags/specific", {
        specific_tag: item.tag,
        generic_tag_id: id,
      });
      if (response.status === 201) state.createdSpecific.add(item.key);
      item.tag = response.data;
    } catch (error) {
      if (error.code !== "SPECIFIC_TAG_MAPPING_CONFLICT") throw error;
    }
    const actual = await exactMapping(item.tag);
    if (!actual) throw new ApiError("映射保存后暂时无法读取，请重试查询。");
    if (genericKey(actual.generic) !== genericKey(target)) {
      item.conflict = { wanted: target, actual };
      throw new ApiError(
        "该来源标签已被映射到其他通用标签，请确认现有映射。",
        "SPECIFIC_TAG_MAPPING_CONFLICT",
      );
    }
    item.mapping = actual;
    item.status = "resolved";
    item.dirty = false;
    saved = true;
    // 同原名的未处理变体下次进入时重新读取候选。
    for (const other of state.items)
      if (
        other !== item &&
        other.tag.site === item.tag.site &&
        other.tag.origin_name === item.tag.origin_name
      )
        other.candidatesLoaded = false;
  } catch (error) {
    item.status = "error";
    item.error = error;
  } finally {
    state.pendingWrites--;
    renderEntry();
  }
  if (saved) {
    announce(`${item.tag.origin_name} 已映射到 ${target.name}`);
    nextItem();
  }
}

function reviewGroups() {
  const genericTags = new Map();
  for (const item of state.items)
    if (item.mapping)
      genericTags.set(genericKey(item.mapping.generic), item.mapping.generic);
  return state.groups
    .filter((group) =>
      [...genericTags.values()].some((tag) => tag.tag_group === group),
    )
    .map((group) =>
      el("div", { class: "review-group" }, [
        el("h3", {}, groupLabel(group)),
        el(
          "div",
          { class: "tag-chips" },
          [...genericTags.values()]
            .filter((tag) => tag.tag_group === group)
            .map((tag) =>
              el("span", { class: "tag-chip" }, [
                tag.name,
                state.createdGeneric.has(genericKey(tag))
                  ? el("small", {}, "本次新增")
                  : null,
              ]),
            ),
        ),
      ]),
    );
}
function renderReview() {
  $("review-panel").replaceChildren(
    el("div", { class: "section-heading review-heading" }, [
      el("div", {}, [
        el("h2", {}, "最后确认一下。"),
        el("p", {}, "来源标签已经完成映射，确认以下分类后即可录入漫画。"),
      ]),
      button(
        "← 返回标签整理",
        () => {
          state.phase = "resolving";
          renderEntry();
        },
        "btn btn-sm btn-outline-secondary",
        { disabled: state.phase === "committing" },
      ),
    ]),
    el(
      "p",
      { class: "review-stats" },
      `${state.items.length} 个独立来源标签 · 本次新建 ${state.createdGeneric.size} 个通用标签、${state.createdSpecific.size} 条来源映射`,
    ),
    ...(state.items.length
      ? reviewGroups()
      : [empty("无需整理标签", "这部漫画的来源数据没有标签，可以直接录入。")]),
  );
}
function renderResult() {
  const success = state.phase === "success";
  $("result-panel").replaceChildren(
    el(
      "div",
      { class: "result-icon", "aria-hidden": "true" },
      success ? "✓" : "ℹ",
    ),
    el("h2", {}, success ? "已收进漫画库" : "这部漫画已经录入"),
    el(
      "p",
      {},
      success
        ? `DMB #${state.comicId} 的漫画与标签关联已保存。`
        : "本次没有覆盖已有漫画。可以返回继续整理其他归档。",
    ),
    el("div", { class: "result-actions" }, [
      el("a", { href: "#/", class: "btn btn-primary" }, "处理下一部 →"),
      button(
        "查看本次标签",
        () => {
          $("result-tags").hidden = !$("result-tags").hidden;
        },
        "btn btn-outline-secondary",
      ),
      button("查看来源数据", showMetadata, "btn btn-quiet"),
    ]),
    el(
      "div",
      { id: "result-tags", hidden: true, class: "mt-4" },
      reviewGroups(),
    ),
    ...(success ? [rawDetails("查看已提交的漫画数据", state.result)] : []),
  );
}
function renderEntry(editor = true) {
  if (state.view !== "entry") return;
  renderSummary();
  renderQueue();
  const finished = ["success", "already-exists"].includes(state.phase);
  const reviewing = ["review", "committing"].includes(state.phase);
  $("workspace").hidden = finished || reviewing;
  $("review-panel").hidden = !reviewing;
  $("result-panel").hidden = !finished;
  $("entry-footer").hidden = finished;
  $("step-tags").className = !reviewing && !finished ? "active" : "complete";
  $("step-review").className = reviewing || finished ? "active" : "";
  $("settings-open").disabled =
    state.pendingWrites > 0 || state.phase === "committing";
  if (reviewing) renderReview();
  else if (finished) renderResult();
  else if (editor) renderEditor();
  $("review-button").disabled = !canCommit();
  $("review-button").textContent =
    state.phase === "committing"
      ? "正在录入…"
      : reviewing
        ? "确认录入漫画"
        : "复核并录入 →";
  $("footer-hint").textContent = state.pendingWrites
    ? "正在保存，请稍候"
    : unresolved().length
      ? `还有 ${unresolved().length} 个标签待处理`
      : "全部标签已映射，可以录入";
}

async function commitComic() {
  if (!canCommit()) return;
  state.phase = "committing";
  state.pendingWrites++;
  state.message = null;
  renderMessage();
  renderEntry();
  let reload = false;
  let missing = null;
  try {
    const { data } = await query(`/comics/${state.comicId}/commit`, {
      source_revision: state.revision,
    });
    state.result = data;
    state.phase = "success";
    announce("漫画录入成功。");
  } catch (error) {
    if (error.code === "COMIC_ALREADY_EXISTS") state.phase = "already-exists";
    else if (error.code === "SOURCE_META_CHANGED") reload = true;
    else if (error.code === "UNMAPPED_SPECIFIC_TAGS") {
      missing = error.details.specific_tags || [];
      state.phase = "resolving";
      message("部分映射已失效，正在重新查询，请确认后再录入。");
    } else {
      state.phase = "review";
      message(error.message, "danger", error, commitComic);
    }
  } finally {
    state.pendingWrites--;
    renderEntry();
  }
  if (reload)
    await loadEntry(
      state.comicId,
      ++routeVersion,
      "来源数据已更新，已重新读取预览。请再次确认标签。",
      true,
    );
  if (missing) {
    const affected = state.items.filter((item) =>
      missing.some((tag) => stableKey(tag) === item.key),
    );
    if (affected.length !== missing.length)
      await loadEntry(
        state.comicId,
        ++routeVersion,
        "来源标签已变化，已重新读取预览。",
        true,
      );
    else {
      state.active = affected[0]?.key || state.active;
      for (const item of affected) {
        item.mapping = null;
        item.candidatesLoaded = false;
      }
      await mapLimit(affected, 6, (item) => resolveItem(item));
    }
  }
}
function showMetadata() {
  $("metadata-content").replaceChildren(
    state.source
      ? rawDetails("DMB 归档记录", state.source, true)
      : el(
          "p",
          { class: "text-secondary" },
          "来源详情未加载，可关闭窗口后重试读取。",
        ),
    rawDetails("Comic 预览", state.preview, !state.source),
  );
  $("metadata-dialog").showModal();
}

async function loadLibrary(offset = 0) {
  libraryController?.abort();
  const controller = (libraryController = new AbortController());
  const group = $("library-group").value;
  if (!group) return;
  $("library-detail").hidden = true;
  libraryDetailController?.abort();
  $("library-results").replaceChildren(
    el("p", { class: "text-secondary p-4" }, "正在查询标签…"),
  );
  $("library-pagination").replaceChildren();
  try {
    const response = await query(
      "/tags/generic/query",
      {
        tag_group: group,
        name: $("library-search").value,
        name_match: "contains",
        limit: 20,
        offset,
      },
      controller.signal,
    );
    const records = await mapLimit(response.data, 6, async (id) => ({
      id,
      tag: (await api(`/tags/generic/${id}`, { signal: controller.signal }))
        .data,
    }));
    if (controller.signal.aborted) return;
    $("library-results").replaceChildren(
      ...(records.length
        ? records.map(({ id, tag }) =>
            el("div", { class: "library-row" }, [
              el("small", {}, `#${id}`),
              el("div", {}, [
                el("strong", {}, tag.name),
                el("small", { class: "d-block" }, groupLabel(tag.tag_group)),
              ]),
              button(
                "查看映射 →",
                () => showGeneric(id),
                "btn btn-sm btn-quiet",
                { "aria-label": `查看 ${tag.name} 的来源映射` },
              ),
            ]),
          )
        : [
            empty(
              "当前分类下没有匹配标签",
              "调整搜索条件，或新建一个通用标签。",
            ),
          ]),
    );
    const total = Number(response.headers.get("X-Total-Count"));
    $("library-pagination").replaceChildren(
      el("span", {}, `共 ${total} 项`),
      button("上一页", () => loadLibrary(offset - 20), "btn btn-sm btn-quiet", {
        disabled: offset === 0,
      }),
      button("下一页", () => loadLibrary(offset + 20), "btn btn-sm btn-quiet", {
        disabled: offset + 20 >= total,
      }),
    );
  } catch (error) {
    if (!controller.signal.aborted)
      $("library-results").replaceChildren(
        errorBox(error, () => loadLibrary(offset)),
      );
  }
}
async function showGeneric(id, offset = 0) {
  libraryDetailController?.abort();
  const controller = (libraryDetailController = new AbortController());
  const node = $("library-detail");
  node.hidden = false;
  node.replaceChildren(el("p", {}, "正在读取来源映射…"));
  try {
    const { data: generic } = await api(`/tags/generic/${id}`, {
      signal: controller.signal,
    });
    const response = await api(
      `/tags/generic/${id}/specifics?limit=20&offset=${offset}`,
      { signal: controller.signal },
    );
    const tags = await mapLimit(
      response.data,
      6,
      async (id) =>
        (await api(`/tags/specific/${id}`, { signal: controller.signal })).data,
    );
    if (controller.signal.aborted) return;
    node.replaceChildren(
      el("div", { class: "section-heading" }, [
        el("div", {}, [
          el("h2", {}, generic.name),
          el(
            "p",
            {},
            `${groupLabel(generic.tag_group)} · ${response.headers.get("X-Total-Count")} 条来源映射`,
          ),
        ]),
        button(
          "收起",
          () => {
            node.hidden = true;
          },
          "btn btn-sm btn-quiet",
        ),
      ]),
      ...(tags.length
        ? tags.map((tag) =>
            el("div", { class: "source-card" }, [
              el("strong", {}, tag.origin_name),
              metadataFields(tag),
              rawDetails("完整来源标签", tag),
            ]),
          )
        : [empty("尚无来源标签映射")]),
      el("div", { class: "pagination-bar" }, [
        button(
          "上一页",
          () => showGeneric(id, offset - 20),
          "btn btn-sm btn-quiet",
          { disabled: offset === 0 },
        ),
        button(
          "下一页",
          () => showGeneric(id, offset + 20),
          "btn btn-sm btn-quiet",
          {
            disabled:
              offset + 20 >= Number(response.headers.get("X-Total-Count")),
          },
        ),
      ]),
    );
    node.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    if (!controller.signal.aborted)
      node.replaceChildren(errorBox(error, () => showGeneric(id, offset)));
  }
}

$("entry-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const value = $("comic-id").value.trim();
  if (!/^\d+$/.test(value) || !Number.isSafeInteger(Number(value))) {
    $("comic-id").setCustomValidity("请输入有效的文档 ID。");
    $("comic-id").reportValidity();
    return;
  }
  location.hash = `#/entry/${Number(value)}`;
});
$("comic-id").addEventListener("input", () =>
  $("comic-id").setCustomValidity(""),
);
$("archive-refresh").addEventListener("click", () => loadArchives());
$("queue-search").addEventListener("input", (event) => {
  state.queueSearch = event.target.value;
  renderQueue();
});
$("queue-status").addEventListener("change", (event) => {
  state.queueStatus = event.target.value;
  renderQueue();
});
$("queue-group").addEventListener("change", (event) => {
  state.queueGroup = event.target.value;
  renderQueue();
});
$("review-button").addEventListener("click", () => {
  if (!canCommit()) return;
  if (state.phase === "review") void commitComic();
  else {
    state.phase = "review";
    renderEntry();
  }
});
$("metadata-open").addEventListener("click", showMetadata);
$("settings-open").addEventListener("click", () => {
  $("dmb-url").value = dmbUrl;
  $("settings-error").textContent = "";
  $("settings-dialog").showModal();
});
$("settings-form").addEventListener("submit", (event) => {
  event.preventDefault();
  try {
    const value = validateDmbUrl($("dmb-url").value.trim());
    if (dirty() && !confirm("更换归档服务会清除当前未保存的选择，是否继续？"))
      return;
    dmbUrl = value;
    localStorage.setItem("comicmanager.dmbUrl", value);
    for (const item of state.items) item.dirty = false;
    $("settings-dialog").close();
    if ((location.hash || "#/") === "#/") void loadArchives(0);
    else location.hash = "#/";
  } catch (error) {
    $("settings-error").textContent = error.message;
  }
});
for (const close of document.querySelectorAll("[data-close-dialog]"))
  close.addEventListener("click", () => close.closest("dialog").close());
$("library-form").addEventListener("submit", (event) => {
  event.preventDefault();
  void loadLibrary();
});
$("library-group").addEventListener("change", () => loadLibrary());
let librarySearchTimer;
$("library-search").addEventListener("input", () => {
  libraryController?.abort();
  clearTimeout(librarySearchTimer);
  librarySearchTimer = setTimeout(() => loadLibrary(), 300);
});
$("library-create-open").addEventListener("click", async () => {
  try {
    await loadGroups(pageController.signal);
    options($("new-tag-group"), $("library-group").value || "", true);
    $("new-tag-name").value = "";
    $("new-tag-error").textContent = "";
    $("new-tag-dialog").showModal();
  } catch (error) {
    message(error.message, "danger", error);
  }
});
$("new-tag-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (state.pendingWrites) return;
  const tag = {
    tag_group: $("new-tag-group").value,
    name: $("new-tag-name").value.trim(),
  };
  if (!state.groups.includes(tag.tag_group) || !tag.name) {
    $("new-tag-error").textContent = "请选择分类并填写名称。";
    return;
  }
  state.pendingWrites++;
  const submit = event.submitter;
  submit.disabled = true;
  try {
    const result = await ensureGeneric(tag);
    $("new-tag-dialog").close();
    $("library-group").value = tag.tag_group;
    $("library-search").value = tag.name;
    message(
      result.created ? "通用标签已创建。" : "同组同名标签已存在，已为你定位。",
      "success",
    );
    await loadLibrary();
  } catch (error) {
    $("new-tag-error").textContent = error.message;
  } finally {
    state.pendingWrites--;
    submit.disabled = false;
  }
});
window.addEventListener("beforeunload", (event) => {
  if (state.pendingWrites || dirty()) {
    event.preventDefault();
    event.returnValue = "";
  }
});
window.addEventListener("hashchange", route);
void route();
