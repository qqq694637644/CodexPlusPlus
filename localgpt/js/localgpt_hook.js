(() => {
  const HOOK_VERSION = "4";
  const REQUEST_MIDDLEWARE_NAME = "localgpt-request";
  const RESPONSE_MIDDLEWARE_NAME = "localgpt-response";
  const requestIdToWorkspaceId = new Map();

  if (window.__localgptHookVersion === HOOK_VERSION) return;
  if (typeof window.__codexPlusRegisterDispatchMiddleware !== "function") {
    throw new Error("LocalGPT 需要 Codex++ dispatch middleware 注册入口");
  }
  if (typeof window.__codexPlusRegisterDispatchResponseMiddleware !== "function") {
    throw new Error("LocalGPT 需要 Codex++ dispatch response middleware 注册入口");
  }
  if (typeof window.__codexSessionDeleteBridge !== "function") {
    throw new Error("LocalGPT 需要 Codex++ bridge");
  }

  function record(event, payload) {
    const item = { at: Date.now(), event, payload };
    if (!window.__localgptLog) window.__localgptLog = [];
    window.__localgptLog.push(item);
    console.debug("[LocalGPT]", event, payload);
  }

  function bridge(path, payload) {
    return window.__codexSessionDeleteBridge(path, payload).then((result) => {
      if (result?.status === "failed") {
        throw new Error(result.message || "LocalGPT bridge failed");
      }
      return result;
    });
  }

  function requestIdOf(message) {
    const requestId = message?.request?.id;
    return requestId === undefined || requestId === null ? "" : String(requestId).trim();
  }

  function paramsOf(message, label) {
    const params = message?.request?.params;
    if (!params || typeof params !== "object") {
      throw new Error(`LocalGPT ${label} 缺少 params`);
    }
    return params;
  }

  function isThreadStartMessage(message) {
    return (
      message?.request?.method === "thread/start" &&
      (message?.type === "mcp-request" || message?.type === "thread-prewarm-start")
    );
  }

  function isTurnStartMessage(message) {
    return message?.type === "mcp-request" && message?.request?.method === "turn/start";
  }

  function withThreadStartEnv(config, venvPath) {
    const nextConfig = { ...(config || {}) };
    const existingSet =
      nextConfig["shell_environment_policy.set"] &&
      typeof nextConfig["shell_environment_policy.set"] === "object"
        ? nextConfig["shell_environment_policy.set"]
        : {};
    nextConfig["shell_environment_policy.inherit"] = "all";
    nextConfig["shell_environment_policy.set"] = {
      ...existingSet,
      VIRTUAL_ENV: venvPath,
    };
    return nextConfig;
  }

  function extractThreadId(response) {
    const candidates = [
      response?.result?.thread?.id,
      response?.thread?.id,
      response?.result?.threadId,
      response?.threadId,
    ];
    for (const candidate of candidates) {
      const value = candidate === undefined || candidate === null ? "" : String(candidate).trim();
      if (value) return value;
    }
    return "";
  }

  async function handleThreadStartRequest(message) {
    const params = paramsOf(message, "thread/start");
    const requestId = requestIdOf(message);
    if (!requestId) throw new Error("LocalGPT thread/start 缺少 request.id");
    if (!params.cwd) throw new Error("LocalGPT thread/start 缺少 cwd");

    const result = await bridge("/localgpt/prepare-thread-start", {
      requestId,
      cwd: params.cwd,
    });

    if (result?.action === "passthrough") {
      record("thread_start.passthrough", {
        requestId,
        cwd: params.cwd,
        reason: result.reason || "",
      });
      return message;
    }

    if (
      result?.action !== "rewrite" ||
      typeof result.workspaceId !== "string" ||
      typeof result.workspace !== "string" ||
      typeof result.venv !== "string" ||
      !result.workspaceId ||
      !result.workspace ||
      !result.venv
    ) {
      throw new Error("LocalGPT prepare-thread-start 返回非法 action");
    }

    requestIdToWorkspaceId.set(requestId, result.workspaceId);
    record("thread_start.rewrite", {
      requestId,
      workspaceId: result.workspaceId,
      originalCwd: params.cwd,
      nextCwd: result.workspace,
      venv: result.venv,
    });

    return {
      ...message,
      request: {
        ...message.request,
        params: {
          ...params,
          cwd: result.workspace,
          workspaceRoots: [result.workspace],
          config: withThreadStartEnv(params.config, result.venv),
        },
      },
    };
  }

  async function handleTurnStartRequest(message) {
    const params = paramsOf(message, "turn/start");
    if (!params.threadId) throw new Error("LocalGPT turn/start 缺少 threadId");
    if (!params.cwd) throw new Error("LocalGPT turn/start 缺少 cwd");

    record("turn_start.observed", {
      threadId: params.threadId,
      cwd: params.cwd,
      inputCount: Array.isArray(params.input) ? params.input.length : null,
    });

    const result = await bridge("/localgpt/prepare-turn-start", {
      threadId: params.threadId,
      cwd: params.cwd,
      input: params.input || [],
    });

    if (result?.action === "passthrough") {
      record("turn_start.passthrough", {
        threadId: params.threadId,
        cwd: params.cwd,
        reason: result.reason || "",
      });
      return message;
    }

    if (result?.action !== "rewrite" || typeof result.cwd !== "string" || !result.cwd) {
      throw new Error("LocalGPT prepare-turn-start 返回非法 action");
    }

    record("turn_start.rewrite", {
      threadId: params.threadId,
      workspaceId: result.workspaceId || "",
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
  }

  window.__codexPlusRegisterDispatchMiddleware(REQUEST_MIDDLEWARE_NAME, (message) => {
    if (isThreadStartMessage(message)) return handleThreadStartRequest(message);
    if (isTurnStartMessage(message)) return handleTurnStartRequest(message);
    return message;
  });

  window.__codexPlusRegisterDispatchResponseMiddleware(RESPONSE_MIDDLEWARE_NAME, async (message, response) => {
    if (!isThreadStartMessage(message)) return response;

    const requestId = requestIdOf(message);
    if (!requestId) throw new Error("LocalGPT thread/start response 缺少 request.id");

    const workspaceId = requestIdToWorkspaceId.get(requestId);
    if (!workspaceId) return response;

    const threadId = extractThreadId(response);
    if (!threadId) {
      throw new Error("LocalGPT thread/start response 缺少 result.thread.id");
    }

    const result = await bridge("/localgpt/commit-thread-start", {
      threadId,
      workspaceId,
    });
    if (result?.action !== "committed") {
      throw new Error("LocalGPT commit-thread-start 返回非法 action");
    }

    requestIdToWorkspaceId.delete(requestId);
    record("thread_start.committed", {
      requestId,
      threadId,
      workspaceId,
      cwd: result.cwd || "",
      statePath: result.statePath || "",
    });
    return response;
  });

  window.__localgptHookVersion = HOOK_VERSION;
  record("install.ok", { version: HOOK_VERSION });
})();
