use std::fs;
use std::path::Path;

use anyhow::{Context, Result, bail};

use crate::paths;
use crate::templates;

pub fn ensure_workspace(thread_id: &str) -> Result<std::path::PathBuf> {
    let workspace = paths::workspace_path(thread_id)?;
    let source_root = paths::source_cwd();
    if workspace.exists() && paths::same_path(&workspace, &source_root)? {
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
    fs::create_dir_all(workspace)
        .with_context(|| format!("创建 workspace 目录失败：{}", workspace.display()))?;

    let agents_path = workspace.join("AGENTS.md");
    let agents_content = templates::agents_template();
    if agents_content.trim().is_empty() {
        bail!("AGENTS.md 模板为空");
    }
    fs::write(&agents_path, agents_content)
        .with_context(|| format!("写入 AGENTS.md 失败：{}", agents_path.display()))?;

    let skills_source = Path::new(env!("CARGO_MANIFEST_DIR")).join("templates").join("skills");
    let skills_target = workspace.join(".agents").join("skills");
    let copied_files = copy_dir_recursive(&skills_source, &skills_target)?;

    validate_existing_workspace(workspace)?;
    if copied_files == 0 {
        bail!("skills 模板目录没有复制任何文件：{}", skills_source.display());
    }

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

fn copy_dir_recursive(source: &Path, destination: &Path) -> Result<usize> {
    if !source.is_dir() {
        bail!("skills 模板目录不存在：{}", source.display());
    }
    fs::create_dir_all(destination)
        .with_context(|| format!("创建 skills 目录失败：{}", destination.display()))?;
    let mut copied_files = 0usize;
    for entry in fs::read_dir(source)
        .with_context(|| format!("读取目录失败：{}", source.display()))?
    {
        let entry = entry?;
        let source_path = entry.path();
        let target_path = destination.join(entry.file_name());
        if source_path.is_dir() {
            copied_files += copy_dir_recursive(&source_path, &target_path)?;
        } else {
            if let Some(parent) = target_path.parent() {
                fs::create_dir_all(parent).with_context(|| {
                    format!("创建目标目录失败：{}", parent.display())
                })?;
            }
            fs::copy(&source_path, &target_path).with_context(|| {
                format!(
                    "复制模板文件失败：{} -> {}",
                    source_path.display(),
                    target_path.display()
                )
            })?;
            copied_files += 1;
        }
    }
    Ok(copied_files)
}
