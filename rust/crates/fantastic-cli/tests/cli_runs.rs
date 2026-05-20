//! Pins that the `fantastic` binary at least builds and exits 0
//! while the scaffold is still in place. Once the real CLI lands
//! (task #229), this expands into one-shot subcommand assertions.

use std::process::Command;

#[test]
fn fantastic_binary_runs_and_exits_zero() {
    let bin = env!("CARGO_BIN_EXE_fantastic");
    let output = Command::new(bin)
        .output()
        .expect("failed to invoke fantastic binary");
    assert!(
        output.status.success(),
        "fantastic exited non-zero: status={:?} stderr={}",
        output.status,
        String::from_utf8_lossy(&output.stderr),
    );
    // Phase 1 scaffold prints a placeholder banner to stderr — assert
    // it's there so a silent regression is loud.
    let stderr = String::from_utf8_lossy(&output.stderr);
    assert!(
        stderr.contains("Phase 1 scaffold"),
        "stderr missing scaffold banner: {stderr}",
    );
}
