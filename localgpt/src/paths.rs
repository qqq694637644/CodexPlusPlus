use anyhow::{Result, bail};
use std::path::{Path, PathBuf};

pub fn repo_root() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("localgpt 应位于仓库根目录下")
        .to_path_buf()
}

pub fn source_cwd() -> PathBuf {
    repo_root()
}

pub fn workspace_root() -> PathBuf {
    repo_root().join("data")
}

pub fn workspace_path(thread_id: &str) -> Result<PathBuf> {
    validate_thread_id(thread_id)?;
    Ok(workspace_root().join(thread_id))
}

pub fn path_key(path: &Path) -> Result<String> {
    let canonical = path.canonicalize()?;
    let mut value = canonical.to_string_lossy().replace('/', "\\");
    if let Some(stripped) = value.strip_prefix(r"\\?\") {
        value = stripped.to_string();
    }
    while value.ends_with('\\') && value.len() > 3 {
        value.pop();
    }
    #[cfg(windows)]
    {
        value = value.to_ascii_lowercase();
    }
    Ok(value)
}

pub fn same_path(left: &Path, right: &Path) -> Result<bool> {
    Ok(path_key(left)? == path_key(right)?)
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
    fn workspace_path_uses_thread_id_as_directory_name() {
        let path = workspace_path("019ed3d7-2a4a-7e02-b92a-2ddb75c9c2ec").unwrap();
        assert!(path.ends_with("019ed3d7-2a4a-7e02-b92a-2ddb75c9c2ec"));
        assert!(!path.ends_with("threadId"));
    }
}
