//! Root orchestrator bundle — the userland id="core" agent at the
//! top of the tree.
//!
//! `core` has no handler_module — system verbs (create_agent,
//! delete_agent, update_agent, list_agents) are native to the Agent
//! class. This crate is mostly the seeded readme + lifecycle hooks.
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
        assert!(README.contains("This is a Fantastic kernel"));
        assert!(README.contains("send(target_id, payload)"));
    }
}
