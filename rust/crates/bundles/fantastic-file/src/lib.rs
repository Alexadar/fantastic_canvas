//! Filesystem-as-agent.
//!
//! Verbs: read, write, list, delete, rename, mkdir. Rooted at the
//! `root` field; path-safety refuses anything escaping it. Files
//! served over HTTP via `/<file_id>/file/<path>`.
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
        assert!(README.contains("file — filesystem as an agent"));
        // The Verbs line is a load-bearing contract — many callers grep it.
        assert!(README.contains("Verbs: read, write, list, delete, rename, mkdir"));
    }
}
