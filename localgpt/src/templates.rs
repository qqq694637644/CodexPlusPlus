use std::path::PathBuf;

use anyhow::{Context, Result, bail};

use crate::paths;

pub fn agents_path() -> Result<PathBuf> {
    Ok(template_root()?.join("AGENTS.md"))
}

pub fn skills_dir() -> Result<PathBuf> {
    Ok(template_root()?.join("skills"))
}

fn template_root() -> Result<PathBuf> {
    Ok(paths::source_cwd()?.join("templates"))
}

pub fn validate() -> Result<()> {
    let root = template_root()?;
    let agents = agents_path()?;
    let skills = skills_dir()?;

    if !root.is_dir() {
        bail!("LocalGPT 模板目录不存在：{}", root.display());
    }
    if !agents.is_file() {
        bail!("LocalGPT 模板缺少 AGENTS.md：{}", agents.display());
    }
    if std::fs::read_to_string(&agents)
        .with_context(|| format!("读取 AGENTS.md 模板失败：{}", agents.display()))?
        .trim()
        .is_empty()
    {
        bail!("AGENTS.md 模板为空：{}", agents.display());
    }
    if !skills.is_dir() {
        bail!("LocalGPT 模板缺少 skills 目录：{}", skills.display());
    }
    Ok(())
}
