use std::collections::BTreeMap;
use std::fs;
use std::path::Path;
use std::sync::{Mutex, OnceLock};

use anyhow::{Context, Result, bail};
use serde::{Deserialize, Serialize};

use crate::paths;

static STATE_LOCK: OnceLock<Mutex<()>> = OnceLock::new();

#[cfg(windows)]
#[link(name = "kernel32")]
unsafe extern "system" {
    fn MoveFileExW(
        lp_existing_file_name: *const u16,
        lp_new_file_name: *const u16,
        dw_flags: u32,
    ) -> i32;
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct LocalGptState {
    #[serde(default)]
    pub threads: BTreeMap<String, String>,
}

pub fn load_state() -> Result<LocalGptState> {
    let _guard = state_lock()
        .lock()
        .map_err(|_| anyhow::anyhow!("LocalGPT 状态锁已中毒"))?;
    load_state_unlocked()
}

pub fn save_state(state: &LocalGptState) -> Result<()> {
    let _guard = state_lock()
        .lock()
        .map_err(|_| anyhow::anyhow!("LocalGPT 状态锁已中毒"))?;
    save_state_unlocked(state)
}

pub fn get_workspace_id(thread_id: &str) -> Result<Option<String>> {
    paths::validate_thread_id(thread_id)?;
    let _guard = state_lock()
        .lock()
        .map_err(|_| anyhow::anyhow!("LocalGPT 状态锁已中毒"))?;
    Ok(load_state_unlocked()?.threads.get(thread_id).cloned())
}

pub fn set_thread_mapping(thread_id: &str, workspace_id: &str) -> Result<()> {
    paths::validate_thread_id(thread_id)?;
    paths::validate_workspace_id(workspace_id)?;

    let _guard = state_lock()
        .lock()
        .map_err(|_| anyhow::anyhow!("LocalGPT 状态锁已中毒"))?;
    let mut state = load_state_unlocked()?;
    if let Some(existing) = state.threads.get(thread_id) {
        if existing != workspace_id {
            bail!(
                "threadId 已绑定到其他 workspace：{} -> {}，拒绝改绑到 {}",
                thread_id,
                existing,
                workspace_id
            );
        }
        return Ok(());
    }

    state
        .threads
        .insert(thread_id.to_string(), workspace_id.to_string());
    save_state_unlocked(&state)
}

fn load_state_unlocked() -> Result<LocalGptState> {
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

fn save_state_unlocked(state: &LocalGptState) -> Result<()> {
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
    replace_state_file(&temp_path, &path)?;
    Ok(())
}

#[cfg(windows)]
fn replace_state_file(temp_path: &Path, path: &Path) -> Result<()> {
    use std::os::windows::ffi::OsStrExt;

    const MOVEFILE_REPLACE_EXISTING: u32 = 0x1;
    const MOVEFILE_WRITE_THROUGH: u32 = 0x8;

    let existing: Vec<u16> = temp_path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let new: Vec<u16> = path
        .as_os_str()
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();
    let ok = unsafe {
        MoveFileExW(
            existing.as_ptr(),
            new.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if ok == 0 {
        bail!(
            "提交 LocalGPT 状态失败：{} -> {}：{}",
            temp_path.display(),
            path.display(),
            std::io::Error::last_os_error()
        );
    }
    Ok(())
}

#[cfg(not(windows))]
fn replace_state_file(temp_path: &Path, path: &Path) -> Result<()> {
    fs::rename(temp_path, path).with_context(|| {
        format!(
            "提交 LocalGPT 状态失败：{} -> {}",
            temp_path.display(),
            path.display()
        )
    })?;
    Ok(())
}

fn state_lock() -> &'static Mutex<()> {
    STATE_LOCK.get_or_init(|| Mutex::new(()))
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
