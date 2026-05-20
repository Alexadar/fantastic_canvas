//! axum HTTP host.
//!
//! Serves `/`, `/<id>/`, `/<id>/file/<path>`, `transport.js`. Call
//! surfaces (WS, REST) live in sibling sub-agents and mount via the
//! duck-typed `get_routes` verb.
//!
//! Phase 1 scaffold; real impl lands with task #229.

#![deny(missing_docs)]

/// readme.md auto-seeded into the agent's dir on creation.
pub const README: &str = include_str!("readme.md");

#[cfg(test)]
mod tests;
