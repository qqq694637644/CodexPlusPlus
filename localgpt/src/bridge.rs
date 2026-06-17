use std::path::Path;

use serde::Deserialize;
use serde_json::{Value, json};

use crate::bootstrap;
use crate::log;
use crate::paths;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PrepareTurnStartRequest {
    thread_id: Option<String>,
    cwd: Option<String>,
    #[allow(dead_code)]
    input: Option<Value>,
}

pub fn handle_bridge(payload: Value) -> anyhow::Result<Value> {
    log::append("bridge.request", json!({ "payload": payload.clone() }));
    let result = handle_bridge_inner(payload);
    match &result {
        Ok(value) => log::append("bridge.response", json!({ "result": value.clone() })),
        Err(error) => log::append("bridge.error", json!({ "message": error.to_string() })),
    }
    result
}

fn handle_bridge_inner(payload: Value) -> anyhow::Result<Value> {
    let request: PrepareTurnStartRequest = serde_json::from_value(payload)?;
    let thread_id = request
        .thread_id
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| anyhow::anyhow!("turn/start 缺少 threadId"))?;

    let cwd = request
        .cwd
        .as_deref()
        .map(str::trim)
        .filter(|value| !value.is_empty())
        .ok_or_else(|| anyhow::anyhow!("turn/start 缺少 cwd"))?;

    let source_cwd = paths::source_cwd();
    let incoming_cwd = Path::new(cwd);
    let incoming_key = paths::path_key(incoming_cwd);
    let source_key = paths::path_key(&source_cwd);

    if !paths::same_path(incoming_cwd, &source_cwd) {
        return Ok(json!({
            "action": "passthrough",
            "threadId": thread_id,
            "reason": "cwd_mismatch",
            "incomingCwd": cwd,
            "incomingKey": incoming_key,
            "sourceCwd": paths::display_path(&source_cwd),
            "sourceKey": source_key,
        }));
    }

    let workspace = bootstrap::ensure_workspace()?;
    Ok(json!({
        "action": "rewrite",
        "threadId": thread_id,
        "cwd": paths::display_path(&workspace),
        "sourceCwd": paths::display_path(&source_cwd),
        "incomingCwd": cwd,
    }))
}
