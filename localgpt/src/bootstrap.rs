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
    let tmp_workspace = tmp_workspace_path(workspace)?;
    if tmp_workspace.exists() {
        fs::remove_dir_all(&tmp_workspace)
            .with_context(|| format!("删除残留临时 workspace 失败：{}", tmp_workspace.display()))?;
    }

    let result = bootstrap_tmp_workspace(&tmp_workspace).and_then(|_| {
        if workspace.exists() {
            bail!("workspace 已存在，拒绝覆盖：{}", workspace.display());
        }
        fs::rename(&tmp_workspace, workspace).with_context(|| {
            format!(
                "发布 workspace 失败：{} -> {}",
                tmp_workspace.display(),
                workspace.display()
            )
        })
    });

    if result.is_err() && tmp_workspace.exists() {
        let _ = fs::remove_dir_all(&tmp_workspace);
    }

    result
}

fn bootstrap_tmp_workspace(workspace: &Path) -> Result<()> {
    fs::create_dir_all(workspace)
        .with_context(|| format!("创建临时 workspace 目录失败：{}", workspace.display()))?;

    let agents_path = workspace.join("AGENTS.md");
    let agents_content = templates::agents_template();
    if agents_content.trim().is_empty() {
        bail!("AGENTS.md 模板为空");
    }
    fs::write(&agents_path, agents_content)
        .with_context(|| format!("写入 AGENTS.md 失败：{}", agents_path.display()))?;

    let skill_content = templates::workspace_skill_template();
    if skill_content.trim().is_empty() {
        bail!("localgpt-workspace skill 模板为空");
    }
    let skill_path = workspace
        .join(".agents")
        .join("skills")
        .join("localgpt-workspace")
        .join("SKILL.md");
    if let Some(parent) = skill_path.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("创建 skill 目录失败：{}", parent.display()))?;
    }
    fs::write(&skill_path, skill_content)
        .with_context(|| format!("写入 skill 失败：{}", skill_path.display()))?;

    validate_existing_workspace(workspace)?;

    Ok(())
}

fn tmp_workspace_path(workspace: &Path) -> Result<std::path::PathBuf> {
    let name = workspace
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| anyhow::anyhow!("workspace 路径缺少目录名：{}", workspace.display()))?;
    Ok(workspace.with_file_name(format!("{name}.tmp-localgpt-bootstrap")))
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
