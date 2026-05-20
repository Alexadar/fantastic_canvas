//! WebSocket verb channel.
//!
//! Mounts `ws://host/<agent_id>/ws`. Text frame protocol carries
//! call / emit / watch / unwatch / reply / error / event envelopes.
//! Binary frames: `[4-byte BE u32 H][JSON header][raw blob]` for
//! byte-heavy payloads.
//!
//! Phase 1 scaffold; real impl lands with task #229.

#![deny(missing_docs)]

/// readme.md auto-seeded into the agent's dir on creation.
pub const README: &str = include_str!("readme.md");

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn readme_present_and_titled() {
        assert!(!README.is_empty());
        assert!(README.contains("web_ws — WebSocket verb channel"));
    }
}
