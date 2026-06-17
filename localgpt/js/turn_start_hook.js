(() => {
  const HOOK_VERSION = "4";
  const MIDDLEWARE_NAME = "localgpt-turn-start";
  const PROJECT_MOVE_PROJECTION_KEY = "codexProjectMoveProjection";

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

  function projectLabelFromPath(path) {
    const parts = String(path || "").replace(/[\\/]+$/, "").split(/[\\/]+/).filter(Boolean);
    return parts[parts.length - 1] || String(path || "");
  }

  function saveProjectMoveProjection(threadId, sourceCwd) {
    if (!threadId || typeof threadId !== "string") {
      throw new Error("LocalGPT 项目投影缺少 threadId");
    }
    if (!sourceCwd || typeof sourceCwd !== "string") {
      throw new Error("LocalGPT 项目投影缺少 sourceCwd");
    }

    const raw = localStorage.getItem(PROJECT_MOVE_PROJECTION_KEY) || "{}";
    const projection = JSON.parse(raw);
    if (!projection || typeof projection !== "object" || Array.isArray(projection)) {
      throw new Error("LocalGPT 项目投影状态非法");
    }

    projection[threadId] = {
      sessionId: threadId,
      targetKind: "project",
      targetCwd: sourceCwd,
      targetLabel: projectLabelFromPath(sourceCwd),
      title: "",
      sortMs: Date.now(),
      sortMsTrusted: false,
      at: Date.now(),
    };
    localStorage.setItem(PROJECT_MOVE_PROJECTION_KEY, JSON.stringify(projection));

    if (typeof window.__codexProjectMoveApplyProjection === "function") {
      window.__codexProjectMoveApplyProjection();
    }
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

      if (
        result?.action !== "rewrite" ||
        typeof result.cwd !== "string" ||
        typeof result.sourceCwd !== "string" ||
        !result.cwd ||
        !result.sourceCwd
      ) {
        throw new Error("LocalGPT bridge 返回非法 action");
      }

      saveProjectMoveProjection(params.threadId, result.sourceCwd);

      record("turn_start.rewrite", {
        threadId: params.threadId,
        originalCwd: params.cwd,
        nextCwd: result.cwd,
        projectCwd: result.sourceCwd,
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
