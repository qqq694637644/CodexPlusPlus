(() => {
  const HOOK_VERSION = "3";
  const MIDDLEWARE_NAME = "localgpt-turn-start";

  if (window.__localgptTurnStartHookVersion === HOOK_VERSION) return;
  if (typeof window.__codexPlusRegisterDispatchMiddleware !== "function") {
    throw new Error("LocalGPT 需要 Codex++ dispatch middleware 注册入口");
  }
  if (typeof window.__codexSessionDeleteBridge !== "function") {
    throw new Error("LocalGPT 需要 Codex++ bridge");
  }

  function record(event, payload) {
    const item = { at: Date.now(), event, payload };
    if (!window.__localgptTurnStartLog) window.__localgptTurnStartLog = [];
    window.__localgptTurnStartLog.push(item);
    console.debug("[LocalGPT]", event, payload);
  }

  window.__codexPlusRegisterDispatchMiddleware(MIDDLEWARE_NAME, (message) => {
    if (message?.type !== "mcp-request" || message?.request?.method !== "turn/start") {
      return message;
    }

    const params = message.request?.params;
    if (!params || typeof params !== "object") {
      throw new Error("LocalGPT turn/start 缺少 params");
    }
    if (!params.threadId) {
      throw new Error("LocalGPT turn/start 缺少 threadId");
    }
    if (!params.cwd) {
      throw new Error("LocalGPT turn/start 缺少 cwd");
    }

    record("turn_start.observed", {
      threadId: params.threadId,
      cwd: params.cwd,
      inputCount: Array.isArray(params.input) ? params.input.length : null,
    });

    return window.__codexSessionDeleteBridge("/localgpt/prepare-turn-start", {
      threadId: params.threadId,
      cwd: params.cwd,
      input: params.input || [],
    }).then((result) => {
      if (result?.status === "failed") {
        throw new Error(result.message || "LocalGPT bridge failed");
      }

      if (result?.action === "passthrough") {
        record("turn_start.passthrough", {
          threadId: params.threadId,
          cwd: params.cwd,
          reason: result.reason || "",
        });
        return message;
      }

      if (result?.action !== "rewrite" || typeof result.cwd !== "string" || !result.cwd) {
        throw new Error("LocalGPT bridge 返回非法 action");
      }

      record("turn_start.rewrite", {
        threadId: params.threadId,
        originalCwd: params.cwd,
        nextCwd: result.cwd,
      });

      return {
        ...message,
        request: {
          ...message.request,
          params: {
            ...params,
            cwd: result.cwd,
          },
        },
      };
    });
  });

  window.__localgptTurnStartHookVersion = HOOK_VERSION;
  record("install.ok", { version: HOOK_VERSION });
})();
