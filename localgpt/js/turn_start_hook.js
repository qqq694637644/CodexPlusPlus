(() => {
  const PATCH_VERSION = "2";
  if (window.__localgptTurnStartHookVersion === PATCH_VERSION) return;

  function log(event, payload = {}) {
    const item = {
      at: Date.now(),
      event,
      payload,
    };
    if (!window.__localgptTurnStartLog) window.__localgptTurnStartLog = [];
    window.__localgptTurnStartLog.push(item);
    try {
      console.debug("[LocalGPT]", event, payload);
    } catch (_) {}
  }

  async function findDispatcher() {
    const urls = new Set();
    for (const script of Array.from(document.scripts || [])) {
      if (script?.src) urls.add(script.src);
    }
    try {
      for (const entry of performance.getEntriesByType("resource") || []) {
        if (entry?.name) urls.add(entry.name);
      }
    } catch (_) {}

    for (const url of urls) {
      if (!url.includes("/assets/")) continue;
      if (!url.endsWith(".js")) continue;
      if (!url.includes("vscode-api-") && !url.includes("app-server-manager-signals-")) continue;
      let module = null;
      try {
        module = await import(url);
      } catch (_) {
        continue;
      }
      for (const value of Object.values(module || {})) {
        if (value && typeof value.dispatchMessage === "function") return value;
        if (typeof value === "function" && String(value).includes("dispatchMessage")) {
          try {
            const instance = value.getInstance?.();
            if (instance && typeof instance.dispatchMessage === "function") return instance;
          } catch (_) {}
        }
      }
    }
    throw new Error("LocalGPT 找不到 Codex dispatcher");
  }

  async function install() {
    const dispatcher = await findDispatcher();
    if (dispatcher.__localgptOriginalDispatchMessage) {
      window.__localgptTurnStartHookVersion = PATCH_VERSION;
      log("install.skip_existing_patch", { version: PATCH_VERSION });
      return;
    }
    if (typeof window.__codexSessionDeleteBridge !== "function") {
      throw new Error("LocalGPT bridge 不可用");
    }

    dispatcher.__localgptOriginalDispatchMessage = dispatcher.dispatchMessage.bind(dispatcher);
    dispatcher.dispatchMessage = async (type, payload) => {
      if (type !== "mcp-request" || payload?.request?.method !== "turn/start") {
        return dispatcher.__localgptOriginalDispatchMessage(type, payload);
      }

      const params = payload?.request?.params;
      if (!params || typeof params !== "object") {
        const message = "LocalGPT turn/start 缺少 params";
        log("turn_start.error", { message, type });
        throw new Error(message);
      }
      if (!params.threadId) {
        const message = "LocalGPT turn/start 缺少 threadId";
        log("turn_start.error", { message, type, cwd: params.cwd || "" });
        throw new Error(message);
      }
      if (!params.cwd) {
        const message = "LocalGPT turn/start 缺少 cwd";
        log("turn_start.error", { message, type, threadId: params.threadId || "" });
        throw new Error(message);
      }

      log("turn_start.observed", {
        threadId: params.threadId || "",
        cwd: params.cwd || "",
        inputCount: Array.isArray(params.input) ? params.input.length : null,
      });

      const result = await window.__codexSessionDeleteBridge("/localgpt/prepare-turn-start", {
        threadId: params.threadId || "",
        cwd: params.cwd || "",
        input: params.input || [],
      });

      if (result?.action === "passthrough") {
        log("turn_start.passthrough", {
          threadId: params.threadId || "",
          cwd: params.cwd || "",
          reason: result.reason || "",
        });
        return dispatcher.__localgptOriginalDispatchMessage(type, payload);
      }

      if (result?.action === "rewrite" && typeof result.cwd === "string" && result.cwd) {
        log("turn_start.rewrite", {
          threadId: params.threadId || "",
          originalCwd: params.cwd || "",
          nextCwd: result.cwd,
        });
        const nextPayload = {
          ...payload,
          request: {
            ...payload.request,
            params: {
              ...params,
              cwd: result.cwd,
            },
          },
        };
        return dispatcher.__localgptOriginalDispatchMessage(type, nextPayload);
      }

      const message = result?.message || "LocalGPT prepare-turn-start 失败";
      log("turn_start.error", {
        threadId: params.threadId || "",
        cwd: params.cwd || "",
        message,
        result,
      });
      throw new Error(String(message));
    };

    window.__localgptTurnStartHookVersion = PATCH_VERSION;
    log("install.ok", { version: PATCH_VERSION });
  }

  let attempts = 0;
  function installWithRetry() {
    attempts += 1;
    void install().catch((error) => {
      log("install.failed", {
        attempts,
        errorName: error?.name || "",
        errorMessage: error?.message || String(error),
      });
      console.error("[LocalGPT] turn/start hook 安装失败", error);
      if (attempts < 20 && window.__localgptTurnStartHookVersion !== PATCH_VERSION) {
        setTimeout(installWithRetry, 500);
      }
    });
  }

  installWithRetry();
})();
