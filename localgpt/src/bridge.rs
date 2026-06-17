use std::path::Path;

use anyhow::{Result, bail};
use serde::Deserialize;
use serde_json::{Value, json};

use crate::bootstrap;
use crate::paths;
use crate::state;

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PrepareThreadStartRequest {
    request_id: Option<String>,
    cwd: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct CommitThreadStartRequest {
    thread_id: Option<String>,
    workspace_id: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
struct PrepareTurnStartRequest {
    thread_id: Option<String>,
    cwd: Option<String>,
    #[serde(default)]
    #[allow(dead_code)]
    input: Option<Value>,
}

pub fn prepare_thread_start(payload: Value) -> Result<Value> {
    let request: PrepareThreadStartRequest = serde_json::from_value(payload)?;
    let request_id = required_string(request.request_id.as_deref(), "thread/start 缺少 requestId")?;
    let cwd = required_string(request.cwd.as_deref(), "thread/start 缺少 cwd")?;

    let source_cwd = paths::source_cwd()?;
    let incoming_cwd = Path::new(cwd);
    if !paths::is_source_cwd(incoming_cwd)? {
        return Ok(json!({
            "action": "passthrough",
            "requestId": request_id,
            "reason": "cwd_mismatch",
            "incomingCwd": cwd,
            "sourceCwd": paths::display_path(&source_cwd),
        }));
    }

    let prepared = bootstrap::create_workspace_for_thread_start()?;
    Ok(json!({
        "action": "rewrite",
        "requestId": request_id,
        "workspaceId": prepared.workspace_id,
        "workspace": paths::display_path(&prepared.workspace_path),
        "venv": paths::display_path(&prepared.venv_path),
        "sourceCwd": paths::display_path(&source_cwd),
        "incomingCwd": cwd,
    }))
}

pub fn commit_thread_start(payload: Value) -> Result<Value> {
    let request: CommitThreadStartRequest = serde_json::from_value(payload)?;
    let thread_id = required_string(request.thread_id.as_deref(), "thread/start response 缺少 threadId")?;
    let workspace_id = required_string(
        request.workspace_id.as_deref(),
        "thread/start response 缺少 workspaceId",
    )?;

    paths::validate_thread_id(thread_id)?;
    paths::validate_workspace_id(workspace_id)?;
    let workspace = paths::workspace_path(workspace_id)?;
    bootstrap::validate_existing_workspace(&workspace)?;
    let state = state::bind_thread(thread_id, workspace_id)?;

    Ok(json!({
        "action": "committed",
        "threadId": thread_id,
        "workspaceId": workspace_id,
        "cwd": paths::display_path(&workspace),
        "venv": paths::display_path(&paths::venv_path(workspace_id)?),
        "statePath": paths::display_path(&paths::state_path()?),
        "threadCount": state.threads.len(),
    }))
}

pub fn prepare_turn_start(payload: Value) -> Result<Value> {
    let request: PrepareTurnStartRequest = serde_json::from_value(payload)?;
    let thread_id = required_string(request.thread_id.as_deref(), "turn/start 缺少 threadId")?;
    let cwd = required_string(request.cwd.as_deref(), "turn/start 缺少 cwd")?;
    paths::validate_thread_id(thread_id)?;

    if let Some(workspace_id) = state::workspace_id_for_thread(thread_id)? {
        let workspace = paths::workspace_path(&workspace_id)?;
        let venv = paths::venv_path(&workspace_id)?;
        bootstrap::validate_existing_workspace(&workspace)?;
        return Ok(json!({
            "action": "rewrite",
            "threadId": thread_id,
            "workspaceId": workspace_id,
            "cwd": paths::display_path(&workspace),
            "venv": paths::display_path(&venv),
        }));
    }

    let source_cwd = paths::source_cwd()?;
    let incoming_cwd = Path::new(cwd);
    if paths::is_source_cwd(incoming_cwd)? {
        bail!(
            "LocalGPT turn/start 未找到 threadId 映射，拒绝继续使用源目录：{}",
            thread_id
        );
    }

    Ok(json!({
        "action": "passthrough",
        "threadId": thread_id,
        "reason": "cwd_mismatch",
        "incomingCwd": cwd,
        "sourceCwd": paths::display_path(&source_cwd),
    }))
}

fn required_string<'a>(value: Option<&'a str>, message: &str) -> Result<&'a str> {
    let value = value.map(str::trim).filter(|value| !value.is_empty());
    value.ok_or_else(|| anyhow::anyhow!(message.to_string()))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn prepare_turn_rejects_missing_thread_id() {
        let payload = json!({ "cwd": paths::display_path(&paths::source_cwd().unwrap()) });
        assert!(prepare_turn_start(payload).is_err());
    }

    #[test]
    fn prepare_turn_rejects_invalid_thread_id() {
        let payload = json!({
            "threadId": "../bad",
            "cwd": paths::display_path(&paths::source_cwd().unwrap()),
        });
        assert!(prepare_turn_start(payload).is_err());
    }

    #[test]
    fn prepare_turn_non_source_cwd_passthrough() {
        let payload = json!({
            "threadId": "thread-ok",
            "cwd": "Z:\\this\\path\\should\\not\\exist\\localgpt",
        });
        let result = prepare_turn_start(payload).unwrap();
        assert_eq!(result["action"], "passthrough");
    }

    #[test]
    fn prepare_thread_non_source_cwd_passthrough() {
        let payload = json!({
            "requestId": "request-ok",
            "cwd": "Z:\\this\\path\\should\\not\\exist\\localgpt",
        });
        let result = prepare_thread_start(payload).unwrap();
        assert_eq!(result["action"], "passthrough");
    }

    #[test]
    fn commit_rejects_invalid_workspace_id() {
        let payload = json!({
            "threadId": "thread-ok",
            "workspaceId": "thread-ok",
        });
        assert!(commit_thread_start(payload).is_err());
    }
}
