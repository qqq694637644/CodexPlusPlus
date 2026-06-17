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

pub fn workspace_path() -> PathBuf {
    workspace_root().join("threadId")
}

pub fn log_path() -> PathBuf {
    repo_root().join("localgpt").join("logs").join("localgpt.log")
}

pub fn path_key(path: &Path) -> String {
    let canonical = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
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
    value
}

pub fn same_path(left: &Path, right: &Path) -> bool {
    path_key(left) == path_key(right)
}

pub fn display_path(path: &Path) -> String {
    path.to_string_lossy().to_string()
}
