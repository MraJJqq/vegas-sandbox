import { normalizeSignalFeed } from "./signal-feed.mjs";

const DEFAULT_REFRESH_MS = 60_000;
const DEFAULT_MAX_AGE_MS = 30 * 60_000;

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
  const clone = document.createElement("div");
  clone.className = "vegas-signal-lane";
  clone.setAttribute("aria-hidden", "true");
  track.append(primary, clone);
  root.append(track);

  let stopped = false;
  let timer = null;
  let controller = null;
  let lastSignature = null;

  function renderMessage(message, state) {
    primary.replaceChildren();
    clone.replaceChildren();
    const label = document.createElement("span");
    label.className = "vegas-signal-item";
    label.textContent = message;
    primary.append(label);
    clone.append(label.cloneNode(true));
    root.classList.remove("is-moving");
    root.dataset.state = state;
    track.style.removeProperty("--ticker-duration");
    lastSignature = null;
  }

  function renderSymbols(symbols) {
    const items = symbols.length ? symbols : ["𝐍𝐨 𝐒𝐢𝐠𝐧𝐚𝐥"];
    primary.replaceChildren();
    clone.replaceChildren();
    for (const symbol of items) {
      const item = document.createElement("span");
      item.className = "vegas-signal-item";
      item.textContent = symbol;
      primary.append(item);
      clone.append(item.cloneNode(true));
    }
    const signature = items.join("|");
    root.classList.toggle("is-moving", symbols.length > 0);
    const duration = Math.max(18, Math.min(90, items.join(" ▰ ").length * 0.75));
    track.style.setProperty("--ticker-duration", duration + "s");
    root.dataset.state = "ready";
    lastSignature = signature;
  }

  async function refresh() {
    if (stopped || document.hidden) return;
    controller?.abort();
    const requestController = new AbortController();
    controller = requestController;
    try {
      const response = await fetch(feedUrl, {
        cache: "no-store",
        headers: { Accept: "application/json" },
        signal: requestController.signal
      });
      if (!response.ok) throw new Error("Signal feed HTTP " + response.status);
      const feed = normalizeSignalFeed(await response.json(), Date.now(), maxAgeMs);
      if (stopped || requestController.signal.aborted) return;
      const signature = feed.symbols.length ? feed.symbols.join("|") : "𝐍𝐨 𝐒𝐢𝐠𝐧𝐚𝐥";
      if (signature !== lastSignature || root.dataset.state !== "ready") {
        renderSymbols(feed.symbols);
      } else {
        root.dataset.state = "ready";
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
      root.classList.remove("vegas-signal-ticker", "is-moving");
    }
  };
}
