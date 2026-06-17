use std::collections::BTreeMap;
use std::fs;

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};

use crate::paths;

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalGptState {
    #[serde(default)]
    pub threads: BTreeMap<String, String>,
}

pub fn load() -> Result<LocalGptState> {
    let path = paths::state_path()?;
    if !path.exists() {
        return Ok(LocalGptState::default());
    }
    let raw = fs::read_to_string(&path)
        .with_context(|| format!("读取 LocalGPT 状态失败：{}", path.display()))?;
    let state: LocalGptState = serde_json::from_str(&raw)
        .with_context(|| format!("解析 LocalGPT 状态失败：{}", path.display()))?;
    validate(&state)?;
    Ok(state)
}

pub fn workspace_id_for_thread(thread_id: &str) -> Result<Option<String>> {
    paths::validate_thread_id(thread_id)?;
    Ok(load()?.threads.get(thread_id).cloned())
}

pub fn bind_thread(thread_id: &str, workspace_id: &str) -> Result<LocalGptState> {
    paths::validate_thread_id(thread_id)?;
    paths::validate_workspace_id(workspace_id)?;

    let mut state = load()?;
    if let Some(existing) = state.threads.get(thread_id) {
        if existing != workspace_id {
            bail!(
                "threadId 已绑定到其他 workspace：{} -> {}，拒绝改绑到 {}",
                thread_id,
                existing,
                workspace_id
            );
        }
    } else {
        state
            .threads
            .insert(thread_id.to_string(), workspace_id.to_string());
        save(&state)?;
    }
    Ok(state)
}

fn save(state: &LocalGptState) -> Result<()> {
    validate(state)?;
    let path = paths::state_path()?;
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("创建 LocalGPT 状态目录失败：{}", parent.display()))?;
    }

    let temp_path = path.with_file_name("localgpt-state.json.tmp");
    if temp_path.exists() {
        bail!("发现未完成的状态写入临时文件：{}", temp_path.display());
    }

    let json = serde_json::to_string_pretty(state)? + "\n";
    fs::write(&temp_path, json)
        .with_context(|| format!("写入 LocalGPT 状态临时文件失败：{}", temp_path.display()))?;

    if path.exists() {
        fs::remove_file(&path)
            .with_context(|| format!("替换 LocalGPT 状态前删除旧文件失败：{}", path.display()))?;
    }
    fs::rename(&temp_path, &path).with_context(|| {
        format!(
            "提交 LocalGPT 状态失败：{} -> {}",
            temp_path.display(),
            path.display()
        )
    })?;
    Ok(())
}

fn validate(state: &LocalGptState) -> Result<()> {
    for (thread_id, workspace_id) in &state.threads {
        paths::validate_thread_id(thread_id)
            .with_context(|| format!("状态文件包含非法 threadId：{}", thread_id))?;
        paths::validate_workspace_id(workspace_id)
            .with_context(|| format!("状态文件包含非法 workspaceId：{}", workspace_id))?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn validates_state_ids() {
        let mut state = LocalGptState::default();
        state.threads.insert(
            "019ed5af-d10d-7c12-b3c7-cd81b7b1ea44".to_string(),
            "localgpt-8be71464-be84-49c9-a166-37458d61a674".to_string(),
        );
        validate(&state).unwrap();

        state
            .threads
            .insert("bad/thread".to_string(), "localgpt-not-a-uuid".to_string());
        assert!(validate(&state).is_err());
    }
}
