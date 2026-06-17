pub mod bootstrap;
pub mod bridge;
pub mod paths;
pub mod templates;

use serde_json::Value;

pub async fn handle_bridge(payload: Value) -> anyhow::Result<Value> {
    bridge::handle_bridge(payload)
}

pub fn hook_script() -> &'static str {
    include_str!("../js/turn_start_hook.js")
}
