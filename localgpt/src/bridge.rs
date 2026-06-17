use std::env;
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
}

pub fn prepare_thread_start(payload: Value) -> Result<Value> {
    let request: PrepareThreadStartRequest = serde_json::from_value(payload)?;
    let request_id = required_string(request.request_id.as_deref(), "thread/start 缺少 requestId")?;
    let cwd = required_string(request.cwd.as_deref(), "thread/start 缺少 cwd")?;

    let incoming_cwd = Path::new(cwd);
    if !paths::is_source_cwd(incoming_cwd)? {
        return Ok(json!({
            "action": "passthrough",
            "reason": "cwd_mismatch",
        }));
    }

    let workspace = bootstrap::create_workspace_for_thread_start()?;
    let venv_scripts = paths::display_path(&workspace.venv_scripts);
    let next_path = path_with_venv_scripts(&venv_scripts)?;

    Ok(json!({
        "action": "rewrite",
        "requestId": request_id,
        "workspaceId": workspace.workspace_id,
        "workspace": paths::display_path(&workspace.workspace),
        "venv": paths::display_path(&workspace.venv),
        "venvScripts": venv_scripts,
        "path": next_path,
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
    state::set_thread_mapping(thread_id, workspace_id)?;

    Ok(json!({
        "status": "ok",
        "threadId": thread_id,
        "workspaceId": workspace_id,
    }))
}

pub fn prepare_turn_start(payload: Value) -> Result<Value> {
    let request: PrepareTurnStartRequest = serde_json::from_value(payload)?;
    let thread_id = required_string(request.thread_id.as_deref(), "turn/start 缺少 threadId")?;
    let cwd = required_string(request.cwd.as_deref(), "turn/start 缺少 cwd")?;
    paths::validate_thread_id(thread_id)?;

    if let Some(workspace_id) = state::get_workspace_id(thread_id)? {
        let workspace = paths::workspace_path(&workspace_id)?;
        bootstrap::validate_existing_workspace(&workspace)?;
        return Ok(json!({
            "action": "rewrite",
            "threadId": thread_id,
            "workspaceId": workspace_id,
            "cwd": paths::display_path(&workspace),
        }));
    }

    let incoming_cwd = Path::new(cwd);
    if paths::is_source_cwd(incoming_cwd)? {
        bail!(
            "LocalGPT turn/start 未找到 threadId 映射，拒绝继续使用源目录：{}",
            thread_id
        );
    }

    Ok(json!({
        "action": "passthrough",
        "reason": "cwd_mismatch",
    }))
}

fn path_with_venv_scripts(venv_scripts: &str) -> Result<String> {
    let inherited_path = inherited_path()?;
    Ok(format!("{};{}", venv_scripts, inherited_path))
}

fn inherited_path() -> Result<String> {
    let value = env::var_os("PATH")
        .or_else(|| env::var_os("Path"))
        .map(|value| value.to_string_lossy().trim().to_string())
        .filter(|value| !value.is_empty())
        .ok_or_else(|| anyhow::anyhow!("LocalGPT 无法读取后端进程 PATH"))?;
    Ok(value)
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

    #[test]
    fn path_with_venv_scripts_keeps_original_path() {
        let value = path_with_venv_scripts(r"D:\repo\data\localgpt-x\.venv\Scripts").unwrap();
        assert!(value.starts_with(r"D:\repo\data\localgpt-x\.venv\Scripts;"));
    }
}
