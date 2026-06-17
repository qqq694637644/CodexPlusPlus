pub mod bootstrap;
pub mod bridge;
pub mod config;
pub mod paths;
pub mod state;
pub mod templates;

use serde_json::Value;

/// Backward-compatible bridge entrypoint for older generated runtimes.
pub async fn handle_bridge(payload: Value) -> anyhow::Result<Value> {
    bridge::prepare_turn_start(payload)
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
