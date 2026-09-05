import { request } from "./entry-api.js?v=reader-blob-1";

// 整部预读保留压缩图片数据；仅显示当前页时解码，避免同时解码整部漫画。
export async function loadReaderPage(getUrl, signal) {
  const remoteUrl = await getUrl(signal);
  signal.throwIfAborted();
  const { data: blob } = await request(remoteUrl, {
    external: true,
    responseType: "blob",
    signal,
  });
  signal.throwIfAborted();
  if (!blob.size) throw new Error("图片内容为空，请重试。");
  return { url: URL.createObjectURL(blob), bytes: blob.size };
}

export function createReaderImageCache({
  keys,
  load,
  release = (page) => URL.revokeObjectURL(page.url),
  onChange = () => {},
  timeoutMs = 30000,
}) {
  const pageKeys = [...new Set(keys)];
  const entries = new Map();
  const failed = new Set();
  let queue = [...pageKeys];
  let activeEntry = null;
  let current;
  let started = false;
  let disposed = false;

  function stats() {
    const values = [...entries.values()];
    return {
      ready: values.filter((entry) => entry.page).length,
      total: pageKeys.length,
      pending: queue.length + Number(!!activeEntry),
      failed: failed.size,
      bytes: values.reduce((sum, entry) => sum + (entry.page?.bytes || 0), 0),
    };
  }
  function changed() {
    if (!disposed) onChange(stats());
  }
  function entryFor(key) {
    let entry = entries.get(key);
    if (!entry) {
      entry = { key, controller: new AbortController() };
      entry.promise = new Promise((resolve, reject) => {
        entry.resolve = resolve;
        entry.reject = reject;
      });
      // 后台预读没有前台等待者，失败交给统计和当前页的显式重试处理。
      void entry.promise.catch(() => {});
      entries.set(key, entry);
    }
    return entry;
  }
  function pump() {
    if (disposed || activeEntry || !queue.length) return;
    const requested = queue.indexOf(current);
    const [key] = queue.splice(requested < 0 ? 0 : requested, 1);
    const entry = entryFor(key);
    activeEntry = entry;
    entry.timer = setTimeout(() => {
      const error = new DOMException("图片加载超时，请重试。", "TimeoutError");
      if (entries.get(key) === entry) entries.delete(key);
      failed.add(key);
      entry.controller.abort(error);
      entry.reject(error);
      changed();
    }, timeoutMs);
    changed();
    Promise.resolve()
      .then(() => {
        entry.controller.signal.throwIfAborted();
        return load(key, entry.controller.signal);
      })
      .then((page) => {
        if (
          disposed ||
          entry.controller.signal.aborted ||
          entries.get(key) !== entry
        ) {
          release(page);
          return;
        }
        entry.page = page;
        failed.delete(key);
        entry.resolve(page);
      })
      .catch((error) => {
        if (entries.get(key) === entry) {
          entries.delete(key);
          if (!disposed) failed.add(key);
        }
        entry.reject(error);
      })
      .finally(() => {
        clearTimeout(entry.timer);
        if (activeEntry === entry) activeEntry = null;
        changed();
        pump();
      });
  }
  function show(key) {
    if (disposed)
      return Promise.reject(new DOMException("阅读已结束。", "AbortError"));
    if (!pageKeys.includes(key))
      return Promise.reject(new Error("无效的漫画页。"));
    if (!started) {
      const start = pageKeys.indexOf(key);
      queue = [...pageKeys.slice(start), ...pageKeys.slice(0, start)];
      started = true;
    }
    current = key;
    const entry = entryFor(key);
    if (!entry.page && activeEntry !== entry) {
      if (!queue.includes(key)) queue.unshift(key);
      if (
        activeEntry &&
        !activeEntry.page &&
        !activeEntry.controller.signal.aborted
      ) {
        // 跳到尚未缓存的页面时先加载当前页，随后继续被中断的预读。
        const previous = activeEntry;
        if (entries.get(previous.key) === previous)
          entries.delete(previous.key);
        if (!queue.includes(previous.key)) queue.unshift(previous.key);
        previous.controller.abort();
        clearTimeout(previous.timer);
        previous.reject(previous.controller.signal.reason);
      }
    }
    pump();
    return entry.promise;
  }
  return {
    show,
    stats,
    peek: (key) => entries.get(key)?.page || null,
    invalidate(key) {
      const entry = entries.get(key);
      if (!entry?.page) return;
      release(entry.page);
      entries.delete(key);
      failed.add(key);
      changed();
    },
    clear() {
      disposed = true;
      queue = [];
      for (const entry of entries.values()) {
        clearTimeout(entry.timer);
        entry.controller.abort();
        entry.reject(entry.controller.signal.reason);
        if (entry.page) release(entry.page);
      }
      entries.clear();
    },
  };
}
