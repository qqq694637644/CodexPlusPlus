from __future__ import annotations

import argparse
import json
import time

from playwright.sync_api import sync_playwright


INSTALL_JS = r"""
async ({ marker }) => {
  const result = { ok: false, error: "", dispatcherSource: "", marker };
  try {
    if (!window.__localgptCancelDispatchLog) window.__localgptCancelDispatchLog = [];

    async function assetUrls() {
      const urls = new Set();
      for (const script of Array.from(document.scripts || [])) if (script.src) urls.add(script.src);
      for (const link of Array.from(document.querySelectorAll("link[href]"))) if (link.href) urls.add(link.href);
      try {
        for (const entry of performance.getEntriesByType("resource") || []) if (entry.name) urls.add(entry.name);
      } catch (_) {}
      return Array.from(urls).filter((url) => url.includes("/assets/") && url.endsWith(".js"));
    }

    let dispatcher = null;
    let dispatcherSource = "";
    for (const url of await assetUrls()) {
      if (!url.includes("vscode-api-") && !url.includes("app-server-manager-signals-")) continue;
      let module = null;
      try { module = await import(url); } catch (_) { continue; }
      for (const [key, value] of Object.entries(module)) {
        if (value && typeof value.dispatchMessage === "function") {
          dispatcher = value;
          dispatcherSource = `${url}#${key}`;
          break;
        }
        if (typeof value === "function" && String(value).includes("dispatchMessage")) {
          try {
            const instance = value.getInstance?.();
            if (instance && typeof instance.dispatchMessage === "function") {
              dispatcher = instance;
              dispatcherSource = `${url}#${key}.getInstance()`;
              break;
            }
          } catch (_) {}
        }
      }
      if (dispatcher) break;
    }
    if (!dispatcher) throw new Error("找不到 dispatcher");

    const original =
      dispatcher.__localgptCancelDispatchOriginal ||
      dispatcher.__localgptBridgeWaitRewriteOriginal ||
      dispatcher.__localgptAsyncCwdRewriteOriginal ||
      dispatcher.__localgptCwdRewriteOriginal ||
      dispatcher.__localgptOriginalDispatchMessage ||
      dispatcher.dispatchMessage.bind(dispatcher);
    dispatcher.__localgptCancelDispatchOriginal = original;
    dispatcher.__localgptCancelDispatchConfig = { marker, cancelled: 0 };

    dispatcher.dispatchMessage = (type, payload) => {
      const config = dispatcher.__localgptCancelDispatchConfig;
      try {
        const method = payload?.request?.method || "";
        const asJson = JSON.stringify(payload || {});
        const hasMarker = asJson.includes(config.marker);
        const isThreadStart = type === "thread-prewarm-start" && method === "thread/start";
        const isTurnStart = type === "mcp-request" && method === "turn/start";
        if (hasMarker || isThreadStart || isTurnStart) {
          // 只取消包含 marker 的 turn/start；thread-prewarm-start 里通常没有用户输入，所以不取消。
          if (hasMarker && isTurnStart) {
            config.cancelled += 1;
            window.__localgptCancelDispatchLog.push({
              at: Date.now(),
              phase: "cancel",
              type: String(type || ""),
              method,
              payload,
            });
            console.warn("[LocalGPT cancel probe] cancelled", type, payload);
            return Promise.reject(new Error("LocalGPT probe cancelled turn/start before original dispatch"));
          }
          window.__localgptCancelDispatchLog.push({
            at: Date.now(),
            phase: "observe",
            type: String(type || ""),
            method,
            hasMarker,
          });
        }
      } catch (error) {
        window.__localgptCancelDispatchLog.push({
          at: Date.now(),
          phase: "error",
          type: String(type || ""),
          error: String(error?.stack || error),
        });
      }
      return original(type, payload);
    };

    result.ok = true;
    result.dispatcherSource = dispatcherSource;
    return result;
  } catch (error) {
    result.error = String(error?.stack || error);
    return result;
  }
}
"""


READ_JS = r"""
() => ({
  location: String(location.href || ""),
  title: String(document.title || ""),
  log: window.__localgptCancelDispatchLog || [],
})
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="探测取消 dispatcher turn/start 是否可阻止旧 cwd 执行")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--marker", default="[localgpt-probe-cancel]")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--out", default="_dump/localgpt-cancel-dispatch-probe.json")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        page = next(pg for c in browser.contexts for pg in c.pages if pg.url.startswith("app://"))
        install = page.evaluate(INSTALL_JS, {"marker": args.marker})
        print(json.dumps(install, ensure_ascii=False, indent=2))
        if not install.get("ok"):
            return 1
        print(f"请在 {args.seconds} 秒内发送包含 {args.marker} 的测试消息。")
        time.sleep(args.seconds)
        data = page.evaluate(READ_JS)
        from pathlib import Path
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已保存：{out}")
        print(f"记录数：{len(data.get('log') or [])}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
