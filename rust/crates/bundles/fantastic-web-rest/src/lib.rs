//! REST verb channel.
//!
//! `POST /<self_id>/<target_id>` body=payload → kernel.send → JSON.
//! Browser-pastable shortcuts: `GET /<self_id>/_reflect[/<target>][?readme=1]`.
//!
//! Phase 1 scaffold; real impl lands with task #229.

#![deny(missing_docs)]

/// readme.md auto-seeded into the agent's dir on creation.
pub const README: &str = include_str!("readme.md");

#[cfg(test)]
mod tests;
