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
    if !config.source_cwd.is_absolute() {
        bail!("localgpt config source_cwd 必须是绝对路径");
    }
    if !config.workspace_root.is_absolute() {
        bail!("localgpt config workspace_root 必须是绝对路径");
    }
    Ok(())
}
