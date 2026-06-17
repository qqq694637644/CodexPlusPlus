pub mod bootstrap;
pub mod bridge;
pub mod config;
pub mod paths;
pub mod state;
pub mod templates;

use serde_json::Value;

pub async fn handle_bridge(_payload: Value) -> anyhow::Result<Value> {
    anyhow::bail!("LocalGPT 旧 handle_bridge 入口已废弃，请重新运行 scripts/prepare_副本.py 生成新运行副本")
}

pub async fn prepare_thread_start(payload: Value) -> anyhow::Result<Value> {
    bridge::prepare_thread_start(payload)
}

pub async fn commit_thread_start(payload: Value) -> anyhow::Result<Value> {
    bridge::commit_thread_start(payload)
}

pub async fn prepare_turn_start(payload: Value) -> anyhow::Result<Value> {
    bridge::prepare_turn_start(payload)
}

pub fn hook_script() -> &'static str {
    include_str!("../js/localgpt_hook.js")
}
