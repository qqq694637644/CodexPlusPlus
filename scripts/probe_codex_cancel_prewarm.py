from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


INSTALL_JS = r"""
async () => {
  const result = { ok: false, error: "", dispatcherSource: "" };
  try {
    if (!window.__localgptCancelPrewarmLog) window.__localgptCancelPrewarmLog = [];

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
      dispatcher.__localgptCancelPrewarmOriginal ||
      dispatcher.__localgptCancelDispatchOriginal ||
      dispatcher.__localgptBridgeWaitRewriteOriginal ||
      dispatcher.__localgptAsyncCwdRewriteOriginal ||
      dispatcher.__localgptCwdRewriteOriginal ||
      dispatcher.__localgptOriginalDispatchMessage ||
      dispatcher.dispatchMessage.bind(dispatcher);
    dispatcher.__localgptCancelPrewarmOriginal = original;
    dispatcher.__localgptCancelPrewarmConfig = { remaining: 1 };

    dispatcher.dispatchMessage = (type, payload) => {
      const config = dispatcher.__localgptCancelPrewarmConfig;
      try {
        const method = payload?.request?.method || "";
        const isThreadStart = type === "thread-prewarm-start" && method === "thread/start";
        if (config.remaining > 0 && isThreadStart) {
          config.remaining -= 1;
          window.__localgptCancelPrewarmLog.push({
            at: Date.now(),
            phase: "cancel",
            type: String(type || ""),
            method,
            cwd: payload?.request?.params?.cwd || "",
            payload,
          });
          console.warn("[LocalGPT prewarm cancel probe] cancelled", payload);
          return Promise.reject(new Error("LocalGPT probe cancelled thread/start before original dispatch"));
        }
      } catch (error) {
        window.__localgptCancelPrewarmLog.push({
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
  log: window.__localgptCancelPrewarmLog || [],
})
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="探测取消 thread-prewarm-start 是否可阻止旧 cwd 执行")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--out", default="_dump/localgpt-cancel-prewarm-probe.json")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        page = next(pg for c in browser.contexts for pg in c.pages if pg.url.startswith("app://"))
        install = page.evaluate(INSTALL_JS)
        print(json.dumps(install, ensure_ascii=False, indent=2))
        if not install.get("ok"):
            return 1
        print(f"请在 {args.seconds} 秒内发送任意测试消息。")
        time.sleep(args.seconds)
        data = page.evaluate(READ_JS)
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"已保存：{out}")
        print(f"记录数：{len(data.get('log') or [])}")
        browser.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
