use anyhow::{Result, bail};
use std::path::{Path, PathBuf};

use crate::config;

pub const WORKSPACE_ID_PREFIX: &str = "localgpt-";

pub fn source_cwd() -> Result<PathBuf> {
    Ok(config::load()?.source_cwd)
}

pub fn workspace_root() -> Result<PathBuf> {
    Ok(config::load()?.workspace_root)
}

pub fn state_path() -> Result<PathBuf> {
    Ok(workspace_root()?.join("localgpt-state.json"))
}

pub fn workspace_path(workspace_id: &str) -> Result<PathBuf> {
    validate_workspace_id(workspace_id)?;
    Ok(workspace_root()?.join(workspace_id))
}

pub fn venv_path(workspace_id: &str) -> Result<PathBuf> {
    Ok(workspace_path(workspace_id)?.join(".venv"))
}

pub fn path_key(path: &Path) -> String {
    let mut value = path.as_os_str().to_string_lossy().replace('/', "\\");
    if let Some(stripped) = value.strip_prefix(r"\\?\") {
        value = stripped.to_string();
    }
    while should_trim_trailing_separator(&value) {
        value.pop();
    }
    value.to_ascii_lowercase()
}

pub fn same_path_key(left: &Path, right: &Path) -> bool {
    path_key(left) == path_key(right)
}

pub fn is_source_cwd(path: &Path) -> Result<bool> {
    Ok(same_path_key(path, &source_cwd()?))
}

pub fn display_path(path: &Path) -> String {
    path.to_string_lossy().to_string()
}

pub fn validate_thread_id(thread_id: &str) -> Result<()> {
    if thread_id.is_empty() {
        bail!("threadId 不能为空");
    }
    if thread_id == "." || thread_id == ".." || thread_id.contains("..") {
        bail!("threadId 非法：禁止点目录片段");
    }
    if thread_id
        .chars()
        .any(|ch| !(ch.is_ascii_alphanumeric() || ch == '-' || ch == '_'))
    {
        bail!("threadId 非法：只允许 ASCII 字母、数字、短横线、下划线");
    }
    Ok(())
}

pub fn validate_workspace_id(workspace_id: &str) -> Result<()> {
    let Some(uuid) = workspace_id.strip_prefix(WORKSPACE_ID_PREFIX) else {
        bail!("workspaceId 非法：必须以 localgpt- 开头");
    };
    validate_uuid(uuid).map_err(|error| anyhow::anyhow!("workspaceId 非法：{}", error))
}

fn validate_uuid(uuid: &str) -> Result<()> {
    if uuid.len() != 36 {
        bail!("UUID 长度必须是 36");
    }
    for (index, ch) in uuid.chars().enumerate() {
        let is_hyphen_index = matches!(index, 8 | 13 | 18 | 23);
        if is_hyphen_index {
            if ch != '-' {
                bail!("UUID 第 {} 位必须是短横线", index + 1);
            }
        } else if !ch.is_ascii_hexdigit() {
            bail!("UUID 只能包含十六进制字符和短横线");
        }
    }
    Ok(())
}

fn should_trim_trailing_separator(value: &str) -> bool {
    if !value.ends_with('\\') {
        return false;
    }
    if value.len() <= 1 {
        return false;
    }
    if is_windows_drive_root(value) {
        return false;
    }
    value != r"\\"
}

fn is_windows_drive_root(value: &str) -> bool {
    let bytes = value.as_bytes();
    bytes.len() == 3 && bytes[1] == b':' && bytes[2] == b'\\'
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn thread_id_rejects_path_like_values() {
        assert!(validate_thread_id("").is_err());
        assert!(validate_thread_id("..").is_err());
        assert!(validate_thread_id("a..b").is_err());
        assert!(validate_thread_id("a/b").is_err());
        assert!(validate_thread_id("a\\b").is_err());
        assert!(validate_thread_id("a:b").is_err());
    }

    #[test]
    fn workspace_id_accepts_localgpt_uuid_values() {
        let workspace_id = "localgpt-8be71464-be84-49c9-a166-37458d61a674";
        assert!(validate_workspace_id(workspace_id).is_ok());
        let path = workspace_path(workspace_id).unwrap();
        assert!(path.ends_with(workspace_id));
    }

    #[test]
    fn workspace_id_rejects_legacy_thread_id_values() {
        assert!(validate_workspace_id("019ed3d7-2a4a-7e02-b92a-2ddb75c9c2ec").is_err());
        assert!(validate_workspace_id("localgpt-not-a-uuid").is_err());
        assert!(validate_workspace_id("localgpt-8be71464-be84-49c9-a166-37458d61a674\\bad").is_err());
    }

    #[test]
    fn path_key_normalizes_slashes_case_and_trailing_separator() {
        assert_eq!(
            path_key(Path::new(r"D:/repos/CodexPlusPlus/")),
            path_key(Path::new(r"d:\repos\CodexPlusPlus"))
        );
    }
}
