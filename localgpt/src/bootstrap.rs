use std::fs;
use std::path::Path;

use anyhow::{Context, Result, bail};

use crate::paths;
use crate::templates;

pub fn ensure_workspace(thread_id: &str) -> Result<std::path::PathBuf> {
    let workspace = paths::workspace_path(thread_id)?;
    let source_root = paths::source_cwd()?;
    if workspace.exists() && paths::same_existing_path(&workspace, &source_root)? {
        bail!("workspace 不能等于源目录：{}", workspace.display());
    }
    if workspace.exists() {
        validate_existing_workspace(&workspace)?;
        return Ok(workspace);
    }
    bootstrap_new_workspace(&workspace)?;
    Ok(workspace)
}

fn bootstrap_new_workspace(workspace: &Path) -> Result<()> {
    templates::validate()?;

    fs::create_dir_all(workspace)
        .with_context(|| format!("创建 workspace 目录失败：{}", workspace.display()))?;

    let agents_path = workspace.join("AGENTS.md");
    fs::copy(templates::agents_path()?, &agents_path)
        .with_context(|| format!("复制 AGENTS.md 失败：{}", agents_path.display()))?;

    copy_dir(&templates::skills_dir()?, &workspace.join(".agents").join("skills"))?;

    validate_existing_workspace(workspace)?;

    Ok(())
}

fn validate_existing_workspace(workspace: &Path) -> Result<()> {
    if !workspace.is_dir() {
        bail!("workspace 不是目录：{}", workspace.display());
    }
    let agents_path = workspace.join("AGENTS.md");
    let skills_target = workspace.join(".agents").join("skills");
    if !agents_path.is_file() {
        bail!("workspace 缺少 AGENTS.md：{}", agents_path.display());
    }
    if !skills_target.is_dir() {
        bail!("workspace 缺少 skills 目录：{}", skills_target.display());
    }
    Ok(())
}

fn copy_dir(source: &Path, target: &Path) -> Result<()> {
    if target.exists() {
        bail!("目标 skills 目录已存在：{}", target.display());
    }
    fs::create_dir_all(target)
        .with_context(|| format!("创建 skills 目录失败：{}", target.display()))?;
    for entry in fs::read_dir(source)
        .with_context(|| format!("读取模板 skills 目录失败：{}", source.display()))?
    {
        let entry = entry?;
        let source_path = entry.path();
        let target_path = target.join(entry.file_name());
        let file_type = entry.file_type()?;
        if file_type.is_dir() {
            copy_dir(&source_path, &target_path)?;
        } else if file_type.is_file() {
            fs::copy(&source_path, &target_path).with_context(|| {
                format!(
                    "复制模板文件失败：{} -> {}",
                    source_path.display(),
                    target_path.display()
                )
            })?;
        } else {
            bail!("模板 skills 目录包含非普通文件：{}", source_path.display());
        }
    }
    Ok(())
}
