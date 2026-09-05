import { dmb } from "./entry-api.js";
import { documentPages, pageImageUrl, libraryReturn } from "./comic-library.js";
import {
  createReaderImageCache,
  loadReaderPage,
} from "./reader-image-cache.js";

export function createComicReader({
  el,
  button,
  empty,
  errorBox,
  getDmbUrl,
  getImageRoute,
  setService,
  announce,
}) {
  const root = document.getElementById("reader-page");
  let active = false;
  let pages = [];
  let current = 0;
  let comicId;
  let back;
  let naturalSize = false;
  let imageTimer;
  let imageController;
  let imageCache;
  let stage;
  let status;
  let cacheStatus;
  let pageInput;
  let previous;
  let next;
  let zoom;
  let imageVersion = 0;
  let touchStart;

  function stop() {
    active = false;
    ++imageVersion;
    imageController?.abort();
    imageCache?.clear();
    imageCache = null;
    clearTimeout(imageTimer);
    root.replaceChildren();
  }
  function resetImages() {
    imageCache?.clear();
    const base = getDmbUrl();
    const route = getImageRoute();
    const id = comicId;
    const cache = createReaderImageCache({
      keys: pages.map((page) => page.index),
      load: (index, signal) =>
        loadReaderPage(
          () => pageImageUrl(base, id, index, route, signal),
          signal,
        ),
      onChange: (progress) => {
        if (!active || imageCache !== cache) return;
        cacheStatus.textContent =
          `已缓存 ${progress.ready} / ${progress.total} 页` +
          (progress.pending
            ? " · 预加载中…"
            : progress.failed
              ? ` · ${progress.failed} 页未成功`
              : " · 全部就绪");
      },
    });
    imageCache = cache;
  }
  async function renderImage() {
    const version = ++imageVersion;
    imageController?.abort();
    const controller = (imageController = new AbortController());
    const cache = imageCache;
    const key = pages[current].index;
    clearTimeout(imageTimer);
    previous.disabled = current === 0;
    next.disabled = current === pages.length - 1;
    pageInput.value = current + 1;
    status.textContent = `正在加载第 ${current + 1} 页…`;
    stage.classList.toggle("natural-size", naturalSize);
    zoom.textContent = naturalSize ? "适应窗口" : "原始大小";
    const params = new URLSearchParams({ back });
    if (current) params.set("page", String(current + 1));
    history.replaceState(null, "", `#/read/${comicId}?${params}`);
    function failed(error) {
      if (!active || version !== imageVersion) return;
      ++imageVersion;
      controller.abort();
      clearTimeout(imageTimer);
      stage.classList.remove("is-loading");
      stage.setAttribute("aria-busy", "false");
      status.textContent = `第 ${current + 1} 页加载失败。`;
      stage.replaceChildren(
        el("div", { class: "reader-empty" }, [
          empty("这一页暂时无法加载", error?.message || ""),
          button("重试本页", renderImage, "btn btn-outline-primary"),
        ]),
      );
    }
    imageTimer = setTimeout(failed, 30000);
    stage.setAttribute("aria-busy", "true");
    stage.classList.toggle("is-loading", !cache.peek(key));
    if (!stage.querySelector("img"))
      stage.replaceChildren(
        el("div", { class: "reader-empty" }, empty("正在加载页面…")),
      );
    stage.scrollTo(0, 0);
    let decoding = false;
    try {
      const page = await cache.show(key);
      if (!active || version !== imageVersion) return;
      const image = el("img", {
        alt: `漫画第 ${current + 1} 页`,
        class: "reader-image",
        decoding: "async",
      });
      const abortImage = () => image.removeAttribute("src");
      controller.signal.addEventListener("abort", abortImage, { once: true });
      image.src = page.url;
      decoding = true;
      try {
        await image.decode();
      } finally {
        controller.signal.removeEventListener("abort", abortImage);
      }
      if (!active || version !== imageVersion) return;
      clearTimeout(imageTimer);
      stage.classList.remove("is-loading");
      stage.setAttribute("aria-busy", "false");
      stage.replaceChildren(image);
      status.textContent = `第 ${current + 1} / ${pages.length} 页`;
      announce(`已加载第 ${current + 1} 页。`);
    } catch (error) {
      if (!controller.signal.aborted) {
        if (decoding) cache.invalidate(key);
        failed(error);
      }
    }
  }
  function changePage(delta) {
    if (!active || !pages.length) return;
    const target = Math.max(0, Math.min(pages.length - 1, current + delta));
    if (target !== current) {
      current = target;
      renderImage();
    }
  }
  document.addEventListener("keydown", (event) => {
    if (
      !active ||
      !pages.length ||
      event.isComposing ||
      event.ctrlKey ||
      event.metaKey ||
      event.altKey ||
      event.target.closest("input, select, textarea, [contenteditable], dialog")
    )
      return;
    if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
      event.preventDefault();
      changePage(event.key === "ArrowLeft" ? -1 : 1);
    }
  });

  async function show(id, params, signal) {
    stop();
    active = true;
    pages = [];
    comicId = id;
    back = libraryReturn(params.get("back"));
    naturalSize = false;
    const backlink = el(
      "a",
      { href: back, class: "back-link" },
      "← 返回漫画库",
    );
    root.append(backlink, empty("正在读取漫画页面…"));
    try {
      const { data } = await dmb(getDmbUrl(), `/v1/documents/${id}`, {
        signal,
      });
      if (signal.aborted || !active) return;
      setService(true);
      document.title = `${data.title || `漫画 #${id}`} · 阅读`;
      pages = documentPages(data);
      if (!pages.length) {
        root.replaceChildren(
          backlink,
          empty(
            "暂时没有可阅读的页面",
            ["deleted", "purged"].includes(data.status)
              ? "这部漫画的来源已删除或清理。"
              : "归档尚未提供可读页面，稍后可以重试。",
          ),
          button(
            "重新读取",
            () => show(id, params, signal),
            "btn btn-outline-secondary",
          ),
        );
        return;
      }
      const requestedPage = Number(params.get("page") || 1);
      current =
        Number.isSafeInteger(requestedPage) && requestedPage > 0
          ? Math.min(requestedPage - 1, pages.length - 1)
          : 0;
      previous = button(
        "← 上一页",
        () => changePage(-1),
        "btn btn-outline-secondary",
      );
      next = button(
        "下一页 →",
        () => changePage(1),
        "btn btn-outline-secondary",
      );
      pageInput = el("input", {
        type: "number",
        class: "form-control form-control-sm",
        min: 1,
        max: pages.length,
        step: 1,
        required: true,
        "aria-label": "阅读页码",
      });
      const jump = el(
        "form",
        {
          class: "page-jump",
          onsubmit: (event) => {
            event.preventDefault();
            if (pageInput.reportValidity()) {
              current = pageInput.valueAsNumber - 1;
              renderImage();
            }
          },
        },
        [
          pageInput,
          el("span", {}, `/ ${pages.length} 页`),
          el(
            "button",
            { type: "submit", class: "btn btn-sm btn-quiet" },
            "跳转",
          ),
        ],
      );
      zoom = button(
        "原始大小",
        () => {
          naturalSize = !naturalSize;
          stage.classList.toggle("natural-size", naturalSize);
          zoom.textContent = naturalSize ? "适应窗口" : "原始大小";
        },
        "btn btn-quiet",
      );
      status = el("span", { class: "reader-status", role: "status" });
      cacheStatus = el("span", { class: "reader-status reader-cache-status" });
      stage = el("div", {
        class: "reader-stage",
        tabindex: 0,
        "aria-label": "漫画页面，左右方向键翻页",
      });
      stage.addEventListener(
        "touchstart",
        (event) => {
          touchStart =
            event.touches.length === 1
              ? [event.touches[0].clientX, event.touches[0].clientY]
              : null;
        },
        { passive: true },
      );
      stage.addEventListener(
        "touchend",
        (event) => {
          if (!touchStart || naturalSize || event.changedTouches.length !== 1)
            return;
          const dx = event.changedTouches[0].clientX - touchStart[0];
          const dy = event.changedTouches[0].clientY - touchStart[1];
          touchStart = null;
          if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy) * 1.5)
            changePage(dx > 0 ? -1 : 1);
        },
        { passive: true },
      );
      root.replaceChildren(
        el("div", { class: "reader-heading" }, [
          backlink,
          el("h1", {}, data.title || `漫画 #${id}`),
        ]),
        el("div", { class: "reader-controls" }, [previous, jump, next, zoom]),
        stage,
        el("div", { class: "reader-status-row" }, [status, cacheStatus]),
      );
      resetImages();
      renderImage();
    } catch (error) {
      if (signal.aborted || !active) return;
      setService(false);
      root.replaceChildren(
        backlink,
        errorBox(error, () => show(id, params, signal)),
      );
    }
  }
  return {
    show,
    stop,
    refreshImage: () => {
      if (active && pages.length) {
        resetImages();
        void renderImage();
      }
    },
  };
}
