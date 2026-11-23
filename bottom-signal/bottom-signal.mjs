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

  root.classList.add("vegas-signal-ticker");
  root.setAttribute("role", "status");
  root.setAttribute("aria-live", "polite");
  root.setAttribute("aria-label", "Vegas signals");
  root.replaceChildren();

  const track = document.createElement("div");
  track.className = "vegas-signal-track";
  const primary = document.createElement("div");
  primary.className = "vegas-signal-lane";
  const duplicate = document.createElement("div");
  duplicate.className = "vegas-signal-lane";
  duplicate.setAttribute("aria-hidden", "true");
  track.append(primary, duplicate);
  root.append(track);

  let stopped = false;
  let timer = null;
  let controller = null;
  let lastSignature = null;
  let currentSymbols = [];

  function renderMessage(message, state) {
    primary.replaceChildren();
    duplicate.replaceChildren();
    const label = document.createElement("span");
    label.className = "vegas-signal-item";
    label.textContent = message;
    primary.append(label);
    duplicate.append(label.cloneNode(true));
    root.classList.remove("is-moving");
    root.dataset.state = state;
    track.style.removeProperty("--ticker-duration");
    lastSignature = null;
  }

  function renderSymbols(symbols) {
    currentSymbols = [...symbols];
    if (!symbols.length) {
      renderMessage("𝐍𝐨 𝐒𝐢𝐠𝐧𝐚𝐥", "ready");
      return;
    }

    primary.replaceChildren();
    const appendSet = () => {
      symbols.forEach((symbol, index) => {
        if (index) {
          const separator = document.createElement("span");
          separator.className = "vegas-signal-separator";
          separator.textContent = "▰";
          primary.append(separator);
        }
        const item = document.createElement("span");
        item.className = "vegas-signal-item";
        item.textContent = symbol;
        primary.append(item);
      });
    };

    appendSet();
    const baseWidth = Math.max(1, primary.scrollWidth);
    const targetWidth = Math.max(root.clientWidth * 1.5, baseWidth);
    let copies = 1;
    while (primary.scrollWidth < targetWidth && copies < 30) {
      appendSet();
      copies += 1;
    }

    duplicate.replaceChildren(...Array.from(primary.children, node => node.cloneNode(true)));
    const laneWidth = Math.max(1, primary.scrollWidth);
    const duration = Math.max(18, Math.min(90, laneWidth / 28));
    track.style.setProperty("--ticker-duration", duration + "s");
    root.classList.add("is-moving");
    root.dataset.state = "ready";
    lastSignature = symbols.join("|");
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
      const signature = feed.symbols.join("|");
      if (signature !== lastSignature || root.dataset.state !== "ready") {
        renderSymbols(feed.symbols);
      }
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

  const resizeObserver = typeof ResizeObserver === "function"
    ? new ResizeObserver(() => {
        if (root.dataset.state === "ready" && currentSymbols.length) {
          renderSymbols(currentSymbols);
        }
      })
    : null;
  resizeObserver?.observe(root);

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
      resizeObserver?.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
      root.replaceChildren();
      delete root.dataset.state;
      delete root.dataset.updated;
      root.classList.remove("vegas-signal-ticker", "is-moving");
    }
  };
}
