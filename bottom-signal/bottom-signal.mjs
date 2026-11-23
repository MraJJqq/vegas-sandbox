import { normalizeSignalFeed } from "./signal-feed.mjs";

const DEFAULT_REFRESH_MS = 60_000;
const DEFAULT_MAX_AGE_MS = 7 * 60 * 60_000;

export function mountBottomSignalTicker({
  root,
  feedUrl,
  refreshMs = DEFAULT_REFRESH_MS,
  maxAgeMs = DEFAULT_MAX_AGE_MS
}) {
  if (!root || !feedUrl) throw new TypeError("root and feedUrl are required");

  root.classList.add("vegas-signal-bar");
  root.setAttribute("role", "status");
  root.setAttribute("aria-live", "polite");
  root.setAttribute("aria-label", "Vegas signals");
  root.replaceChildren();

  const content = document.createElement("div");
  content.className = "vegas-signal-content";
  root.append(content);

  let stopped = false;
  let timer = null;
  let controller = null;

  function renderMessage(message, state) {
    content.replaceChildren();
    const label = document.createElement("span");
    label.className = "vegas-signal-message";
    label.textContent = message;
    content.append(label);
    root.dataset.state = state;
  }

  function renderSymbols(symbols) {
    content.replaceChildren();
    if (!symbols.length) {
      renderMessage("𝐍𝐨 𝐒𝐢𝐠𝐧𝐚𝐥", "ready");
      return;
    }

    symbols.forEach((symbol, index) => {
      if (index) {
        const separator = document.createElement("span");
        separator.className = "vegas-signal-separator";
        separator.textContent = "▰";
        separator.setAttribute("aria-hidden", "true");
        content.append(separator);
      }
      const item = document.createElement("span");
      item.className = "vegas-signal-item";
      item.textContent = symbol;
      content.append(item);
    });
    root.dataset.state = "ready";
  }

  async function refresh() {
    if (stopped || document.hidden) return;
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    try {
      const requestUrl = new URL(feedUrl, location.href);
      requestUrl.searchParams.set("_", String(Date.now()));
      const response = await fetch(requestUrl.toString(), {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: requestController.signal
      });
      if (!response.ok) throw new Error("Signal feed HTTP " + response.status);
      const feed = normalizeSignalFeed(await response.json(), Date.now(), maxAgeMs);
      if (stopped || requestController.signal.aborted) return;
      renderSymbols(feed.symbols);
      root.dataset.updated = feed.generatedAt;
    } catch (error) {
      if (error.name === "AbortError" || stopped) return;
      renderMessage("等待信号数据", "unavailable");
      delete root.dataset.updated;
    } finally {
      if (controller === requestController) controller = null;
    }
  }

  function schedule() {
    if (stopped || document.hidden) return;
    clearTimeout(timer);
    timer = setTimeout(async () => {
      await refresh();
      schedule();
    }, refreshMs);
  }

  function onVisibility() {
    clearTimeout(timer);
    if (document.hidden) {
      controller?.abort();
    } else {
      void refresh();
      schedule();
    }
  }

  document.addEventListener("visibilitychange", onVisibility);
  root.dataset.state = "loading";
  renderMessage("等待信号数据", "loading");
  void refresh();
  schedule();

  return {
    refresh,
    destroy() {
      stopped = true;
      clearTimeout(timer);
      controller?.abort();
      document.removeEventListener("visibilitychange", onVisibility);
      root.replaceChildren();
      delete root.dataset.state;
      delete root.dataset.updated;
      root.classList.remove("vegas-signal-bar");
    }
  };
}
