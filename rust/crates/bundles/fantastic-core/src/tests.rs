//! Unit tests for this bundle crate.

use super::*;

#[test]
fn readme_present_and_titled() {
    assert!(!README.is_empty());
    assert!(README.contains("This is a Fantastic kernel"));
    assert!(README.contains("send(target_id, payload)"));
}
