from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


INSTALL_JS = r"""
async ({ targetCwd, marker }) => {
  const result = { ok: false, error: "", dispatcherSource: "", targetCwd, marker };
  try {
    if (!window.__localgptTurnOnlyRewriteLog) window.__localgptTurnOnlyRewriteLog = [];

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
      dispatcher.__localgptTurnOnlyRewriteOriginal ||
      dispatcher.__localgptCancelPrewarmOriginal ||
      dispatcher.__localgptCancelDispatchOriginal ||
      dispatcher.__localgptBridgeWaitRewriteOriginal ||
      dispatcher.__localgptAsyncCwdRewriteOriginal ||
      dispatcher.__localgptCwdRewriteOriginal ||
      dispatcher.__localgptOriginalDispatchMessage ||
      dispatcher.dispatchMessage.bind(dispatcher);
    dispatcher.__localgptTurnOnlyRewriteOriginal = original;
    dispatcher.__localgptTurnOnlyRewriteConfig = { targetCwd, marker, remaining: 3 };

    dispatcher.dispatchMessage = async (type, payload) => {
      const config = dispatcher.__localgptTurnOnlyRewriteConfig;
      let nextPayload = payload;
      let changed = false;
      try {
        const method = payload?.request?.method || "";
        const params = payload?.request?.params;
        const isThreadStart = type === "thread-prewarm-start" && method === "thread/start";
        const isTurnStart = type === "mcp-request" && method === "turn/start";
        const isTitle = type === "fetch" && String(payload?.url || "").includes("generate-thread-title");
        const asJson = JSON.stringify(payload || "");
        const hasMarker = asJson.includes(config.marker);

        if (isThreadStart) {
          window.__localgptTurnOnlyRewriteLog.push({
            at: Date.now(),
            phase: "observe-prewarm",
            type: String(type || ""),
            cwd: params?.cwd || "",
          });
          return original(type, payload);
        }

        if (config.remaining > 0 && ((isTurnStart && hasMarker) || (isTitle && hasMarker))) {
          if (isTurnStart && params && typeof params === "object") {
            nextPayload = {
              ...payload,
              request: {
                ...payload.request,
                params: {
                  ...params,
                  cwd: config.targetCwd,
                  responsesapiClientMetadata: {
                    ...(params.responsesapiClientMetadata || {}),
                    localgpt_probe: "turn_only_cwd_rewrite",
                  },
                },
              },
            };
            changed = true;
          } else if (isTitle && typeof payload?.body === "string") {
            try {
              const body = JSON.parse(payload.body);
              body.cwd = config.targetCwd;
              nextPayload = { ...payload, body: JSON.stringify(body) };
              changed = true;
            } catch (_) {}
          }
          if (changed) config.remaining -= 1;
        }
      } catch (error) {
        window.__localgptTurnOnlyRewriteLog.push({
          at: Date.now(),
          phase: "error",
          type: String(type || ""),
          error: String(error?.stack || error),
        });
      }

      if (changed) {
        window.__localgptTurnOnlyRewriteLog.push({
          at: Date.now(),
          phase: "rewrite",
          type: String(type || ""),
          originalCwd: payload?.request?.params?.cwd || "",
          nextCwd: targetCwd,
          payload: nextPayload,
        });
      }
      return original(type, nextPayload);
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
  log: window.__localgptTurnOnlyRewriteLog || [],
})
"""


def main() -> int:
    parser = argparse.ArgumentParser(description="探测仅改写 turn/start.cwd 是否加载 AGENTS/skills")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--target-cwd", required=True)
    parser.add_argument("--marker", default="[localgpt-probe-turn-only]")
    parser.add_argument("--seconds", type=int, default=90)
    parser.add_argument("--out", default="_dump/localgpt-turn-only-cwd-rewrite-probe.json")
    args = parser.parse_args()

    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(args.cdp)
        page = next(pg for c in browser.contexts for pg in c.pages if pg.url.startswith("app://"))
        install = page.evaluate(
            INSTALL_JS,
            {
                "targetCwd": str(Path(args.target_cwd).resolve()),
                "marker": args.marker,
            },
        )
        print(json.dumps(install, ensure_ascii=False, indent=2))
        if not install.get("ok"):
            return 1
        print(f"请在 {args.seconds} 秒内发送包含 {args.marker} 的测试消息。")
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
