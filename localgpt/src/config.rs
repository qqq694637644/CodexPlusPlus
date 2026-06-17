use std::path::PathBuf;

use anyhow::{Result, bail};
use serde::Deserialize;

#[derive(Debug, Clone, Deserialize)]
pub struct LocalGptConfig {
    pub source_cwd: PathBuf,
    pub workspace_root: PathBuf,
}

pub fn load() -> Result<LocalGptConfig> {
    let config: LocalGptConfig = serde_json::from_str(include_str!("../config.json"))?;
    validate(&config)?;
    Ok(config)
}

fn validate(config: &LocalGptConfig) -> Result<()> {
    if !is_absolute_config_path(&config.source_cwd) {
        bail!("localgpt config source_cwd 必须是绝对路径");
    }
    if !is_absolute_config_path(&config.workspace_root) {
        bail!("localgpt config workspace_root 必须是绝对路径");
    }
    let expected_workspace_root = normalize_config_path(&config.source_cwd.join("data"));
    let actual_workspace_root = normalize_config_path(&config.workspace_root);
    if actual_workspace_root != expected_workspace_root {
        bail!("localgpt config workspace_root 必须等于 source_cwd\\data");
    }
    Ok(())
}

fn is_absolute_config_path(path: &std::path::Path) -> bool {
    if path.is_absolute() {
        return true;
    }
    let value = path.to_string_lossy();
    let bytes = value.as_bytes();
    bytes.len() >= 3
        && bytes[1] == b':'
        && (bytes[2] == b'\\' || bytes[2] == b'/')
        && bytes[0].is_ascii_alphabetic()
}

fn normalize_config_path(path: &std::path::Path) -> String {
    let mut value = path.to_string_lossy().replace('/', "\\");
    if let Some(stripped) = value.strip_prefix(r"\\?\") {
        value = stripped.to_string();
    }
    while value.ends_with('\\') && value.len() > 3 {
        value.pop();
    }
    value.to_ascii_lowercase()
}
