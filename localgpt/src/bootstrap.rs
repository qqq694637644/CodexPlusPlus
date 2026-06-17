use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

use anyhow::{Context, Result, bail};

use crate::paths;
use crate::templates;

#[cfg(windows)]
#[link(name = "advapi32")]
unsafe extern "system" {
    fn SystemFunction036(
        random_buffer: *mut std::ffi::c_void,
        random_buffer_length: u32,
    ) -> u8;
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceInfo {
    pub workspace_id: String,
    pub workspace: PathBuf,
    pub venv: PathBuf,
    pub venv_scripts: PathBuf,
}

pub fn create_workspace_for_thread_start() -> Result<WorkspaceInfo> {
    let workspace_id = format!("{}{}", paths::WORKSPACE_ID_PREFIX, uuid_v4()?);
    bootstrap_new_workspace(&workspace_id)
}

pub fn bootstrap_new_workspace(workspace_id: &str) -> Result<WorkspaceInfo> {
    paths::validate_workspace_id(workspace_id)?;
    let workspace = paths::workspace_path(workspace_id)?;
    let venv = paths::venv_path(workspace_id)?;
    let venv_scripts = paths::venv_scripts_path(workspace_id)?;
    let source_root = paths::source_cwd()?;

    if paths::same_path_key(&workspace, &source_root) {
        bail!("workspace 不能等于源目录：{}", workspace.display());
    }
    if workspace.exists() {
        bail!("workspace 已存在，拒绝复用或补救：{}", workspace.display());
    }

    bootstrap_workspace_skeleton_transactionally(&workspace)?;
    if let Err(error) = create_python_venv(&venv).and_then(|_| validate_existing_workspace(&workspace)) {
        rollback_workspace_after_failed_venv(&workspace, error)?;
    }

    Ok(WorkspaceInfo {
        workspace_id: workspace_id.to_string(),
        workspace,
        venv,
        venv_scripts,
    })
}

fn bootstrap_workspace_skeleton_transactionally(workspace: &Path) -> Result<()> {
    templates::validate()?;
    let temp_workspace = temp_workspace_path(workspace)?;
    if temp_workspace.exists() {
        bail!(
            "发现未完成的 workspace 初始化目录，拒绝补救：{}",
            temp_workspace.display()
        );
    }
    if let Some(parent) = workspace.parent() {
        fs::create_dir_all(parent)
            .with_context(|| format!("创建 workspace 父目录失败：{}", parent.display()))?;
    }

    bootstrap_workspace_skeleton_contents(&temp_workspace)?;
    validate_workspace_skeleton(&temp_workspace)?;
    fs::rename(&temp_workspace, workspace).with_context(|| {
        format!(
            "提交 workspace 初始化失败：{} -> {}",
            temp_workspace.display(),
            workspace.display()
        )
    })?;

    Ok(())
}

fn bootstrap_workspace_skeleton_contents(workspace: &Path) -> Result<()> {
    fs::create_dir_all(workspace)
        .with_context(|| format!("创建 workspace 目录失败：{}", workspace.display()))?;

    let agents_path = workspace.join("AGENTS.md");
    fs::copy(templates::agents_path()?, &agents_path)
        .with_context(|| format!("复制 AGENTS.md 失败：{}", agents_path.display()))?;

    copy_dir(&templates::skills_dir()?, &workspace.join(".agents").join("skills"))?;

    Ok(())
}

fn create_python_venv(venv_path: &Path) -> Result<()> {
    let output = Command::new("python")
        .arg("-m")
        .arg("venv")
        .arg(venv_path)
        .output()
        .with_context(|| "执行 python -m venv 失败：找不到 python 或无法启动".to_string())?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).trim().to_string();
        let stdout = String::from_utf8_lossy(&output.stdout).trim().to_string();
        bail!(
            "创建 Python venv 失败：{}{}{}",
            venv_path.display(),
            if stderr.is_empty() { "" } else { "；stderr: " },
            if stderr.is_empty() { stdout } else { stderr }
        );
    }

    Ok(())
}

fn rollback_workspace_after_failed_venv(workspace: &Path, original_error: anyhow::Error) -> Result<()> {
    match fs::remove_dir_all(workspace) {
        Ok(()) => Err(anyhow::anyhow!(
            "LocalGPT workspace 初始化失败，已回滚最终目录：{}；原因：{:#}",
            workspace.display(),
            original_error
        )),
        Err(rollback_error) => Err(anyhow::anyhow!(
            "LocalGPT workspace 初始化失败，且回滚最终目录失败：{}；原因：{:#}；回滚错误：{}",
            workspace.display(),
            original_error,
            rollback_error
        )),
    }
}

pub fn validate_existing_workspace(workspace: &Path) -> Result<()> {
    validate_workspace_skeleton(workspace)?;
    let venv_target = workspace.join(".venv");
    let venv_scripts_target = venv_target.join("Scripts");
    if !venv_target.is_dir() {
        bail!("workspace 缺少 .venv 目录：{}", venv_target.display());
    }
    if !venv_scripts_target.is_dir() {
        bail!(
            "workspace 缺少 .venv\\Scripts 目录：{}",
            venv_scripts_target.display()
        );
    }
    Ok(())
}

fn validate_workspace_skeleton(workspace: &Path) -> Result<()> {
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

fn temp_workspace_path(workspace: &Path) -> Result<PathBuf> {
    let name = workspace
        .file_name()
        .ok_or_else(|| anyhow::anyhow!("workspace 路径缺少目录名：{}", workspace.display()))?;
    Ok(workspace.with_file_name(format!(".{}.tmp", name.to_string_lossy())))
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

fn uuid_v4() -> Result<String> {
    let mut bytes = [0_u8; 16];
    fill_random(&mut bytes)?;
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    Ok(format!(
        "{:02x}{:02x}{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}-{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
        bytes[0],
        bytes[1],
        bytes[2],
        bytes[3],
        bytes[4],
        bytes[5],
        bytes[6],
        bytes[7],
        bytes[8],
        bytes[9],
        bytes[10],
        bytes[11],
        bytes[12],
        bytes[13],
        bytes[14],
        bytes[15]
    ))
}

#[cfg(windows)]
fn fill_random(bytes: &mut [u8]) -> Result<()> {
    let ok = unsafe { SystemFunction036(bytes.as_mut_ptr().cast(), bytes.len() as u32) };
    if ok == 0 {
        bail!("生成 workspace UUID 失败：RtlGenRandom 返回失败");
    }
    Ok(())
}

#[cfg(not(windows))]
fn fill_random(bytes: &mut [u8]) -> Result<()> {
    use std::io::Read;

    let mut file = fs::File::open("/dev/urandom").context("打开 /dev/urandom 失败")?;
    file.read_exact(bytes).context("读取 /dev/urandom 失败")?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn uuid_v4_generates_valid_workspace_id_suffix() {
        let workspace_id = format!("{}{}", paths::WORKSPACE_ID_PREFIX, uuid_v4().unwrap());
        paths::validate_workspace_id(&workspace_id).unwrap();
    }
}
