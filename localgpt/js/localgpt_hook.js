(() => {
  const HOOK_VERSION = "5";
  const REQUEST_MIDDLEWARE_NAME = "localgpt-request";
  const INBOUND_MIDDLEWARE_NAME = "localgpt-inbound";
  const requestIdToWorkspaceId = new Map();

  if (window.__localgptHookVersion === HOOK_VERSION) return;
  if (typeof window.__codexPlusRegisterDispatchMiddleware !== "function") {
    throw new Error("LocalGPT 需要 Codex++ dispatch middleware 注册入口");
  }
  if (typeof window.__codexPlusRegisterInboundMiddleware !== "function") {
    throw new Error("LocalGPT 需要 Codex++ inbound middleware 注册入口");
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
    if (!isPlainObject(params)) {
      throw new Error(`LocalGPT ${label} 缺少 params 或 params 类型非法`);
    }
    return params;
  }

  function isPlainObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
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

  function withThreadStartEnv(config, result) {
    if (config !== undefined && config !== null && !isPlainObject(config)) {
      throw new Error("LocalGPT thread/start config 类型非法");
    }

    const currentConfig = config || {};
    const currentSet = currentConfig["shell_environment_policy.set"];
    if (currentSet !== undefined && currentSet !== null && !isPlainObject(currentSet)) {
      throw new Error("LocalGPT thread/start shell_environment_policy.set 类型非法");
    }

    return {
      ...currentConfig,
      "shell_environment_policy.inherit": "all",
      "shell_environment_policy.set": {
        ...(currentSet || {}),
        VIRTUAL_ENV: result.venv,
        PATH: result.path,
      },
    };
  }

  function parseInboundMcpResponse(event) {
    if (event?.data?.type !== "mcp-response") return null;
    const raw = event?.data?.message;
    if (typeof raw !== "string" || !raw.trim()) {
      throw new Error("LocalGPT mcp-response 缺少 message JSON");
    }
    const parsed = JSON.parse(raw);
    if (!isPlainObject(parsed)) {
      throw new Error("LocalGPT mcp-response message 类型非法");
    }
    return parsed;
  }

  function responseIdOf(response) {
    const responseId = response?.id;
    return responseId === undefined || responseId === null ? "" : String(responseId).trim();
  }

  function extractThreadId(response) {
    const threadId = response?.result?.thread?.id;
    return threadId === undefined || threadId === null ? "" : String(threadId).trim();
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
      typeof result.venvScripts !== "string" ||
      typeof result.path !== "string" ||
      !result.workspaceId ||
      !result.workspace ||
      !result.venv ||
      !result.venvScripts ||
      !result.path
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
      venvScripts: result.venvScripts,
    });

    return {
      ...message,
      request: {
        ...message.request,
        params: {
          ...params,
          cwd: result.workspace,
          workspaceRoots: [result.workspace],
          config: withThreadStartEnv(params.config, result),
        },
      },
    };
  }

  async function handleThreadStartResponse(event) {
    const response = parseInboundMcpResponse(event);
    if (!response) return event;

    const responseId = responseIdOf(response);
    if (!responseId || !requestIdToWorkspaceId.has(responseId)) return event;

    const threadId = extractThreadId(response);
    if (!threadId) {
      throw new Error("LocalGPT thread/start response 缺少 result.thread.id");
    }

    const workspaceId = requestIdToWorkspaceId.get(responseId);
    const result = await bridge("/localgpt/commit-thread-start", {
      threadId,
      workspaceId,
    });
    if (result?.status !== "ok") {
      throw new Error("LocalGPT commit-thread-start 返回非法 status");
    }

    requestIdToWorkspaceId.delete(responseId);
    record("thread_start.committed", {
      requestId: responseId,
      threadId,
      workspaceId,
    });
    return event;
  }

  async function handleTurnStartRequest(message) {
    const params = paramsOf(message, "turn/start");
    if (!params.threadId) throw new Error("LocalGPT turn/start 缺少 threadId");
    if (!params.cwd) throw new Error("LocalGPT turn/start 缺少 cwd");

    record("turn_start.observed", {
      threadId: params.threadId,
      cwd: params.cwd,
    });

    const result = await bridge("/localgpt/prepare-turn-start", {
      threadId: params.threadId,
      cwd: params.cwd,
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

  window.__codexPlusRegisterInboundMiddleware(INBOUND_MIDDLEWARE_NAME, (event) => {
    return handleThreadStartResponse(event);
  });

  window.__localgptHookVersion = HOOK_VERSION;
  record("install.ok", { version: HOOK_VERSION });
})();
