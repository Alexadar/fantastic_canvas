//! Ephemeral stdout renderer — composed per-process when stdin is a
//! tty. Never persisted.
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
        assert!(README.contains("cli — stdout renderer"));
    }
}
