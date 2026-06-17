use std::path::Path;

use serde::Deserialize;
use serde_json::{Value, json};

use crate::bootstrap;
use crate::paths;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PrepareTurnStartRequest {
    thread_id: Option<String>,
    cwd: Option<String>,
    #[serde(default)]
    #[allow(dead_code)]
    input: Option<Value>,
}

pub fn handle_bridge(payload: Value) -> anyhow::Result<Value> {
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

    if !paths::same_path(incoming_cwd, &source_cwd)? {
        return Ok(json!({
            "action": "passthrough",
            "threadId": thread_id,
            "reason": "cwd_mismatch",
            "incomingCwd": cwd,
            "sourceCwd": paths::display_path(&source_cwd),
        }));
    }

    let workspace = bootstrap::ensure_workspace(thread_id)?;
    Ok(json!({
        "action": "rewrite",
        "threadId": thread_id,
        "cwd": paths::display_path(&workspace),
        "sourceCwd": paths::display_path(&source_cwd),
        "incomingCwd": cwd,
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_missing_thread_id() {
        let payload = json!({ "cwd": paths::display_path(&paths::source_cwd()) });
        assert!(handle_bridge(payload).is_err());
    }

    #[test]
    fn rejects_invalid_thread_id() {
        let payload = json!({
            "threadId": "../bad",
            "cwd": paths::display_path(&paths::source_cwd()),
        });
        assert!(handle_bridge(payload).is_err());
    }
}
