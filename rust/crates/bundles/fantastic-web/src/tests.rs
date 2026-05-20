//! Unit tests for this bundle crate.

use super::*;

#[test]
fn readme_present_and_titled() {
    assert!(!README.is_empty());
    assert!(README.contains("web — axum HTTP host"));
}
