# cli selftest

> scopes: cli
> requires: `uv sync`
> out-of-scope: any non-renderer verb

Renderer agent. Verifies token/done/say/error print correctly.

## Pre-flight

```bash
cd new_codebase
rm -rf .fantastic
```

## Tests

### Test 1: say with source prefix

```bash
echo "@cli say text=hello source=agent_x" | uv run python kernel.py 2>&1 | grep -F "[agent_x] hello"
```
Expected: line containing `[agent_x] hello`.

### Test 2: token streaming (no newline)

```bash
echo "@cli token text=ABCDEF" | uv run python kernel.py 2>&1 | grep -F "ABCDEF"
```
Expected: ABCDEF appears in output (no trailing newline from token alone).

### Test 3: done emits newline

```bash
{ echo "@cli token text=part1"; echo "@cli done"; echo "exit"; } | uv run python kernel.py
```
Expected: `part1` followed by a newline in output.

### Test 4: error prefixed with ERROR

```bash
echo "@cli error text=boom" | uv run python kernel.py 2>&1 | grep -F "ERROR: boom"
```
Expected: line with `ERROR: boom`.

## Summary

| # | Test | Pass |
|---|------|------|
| 1 | say with source prefix | |
| 2 | token (no newline) | |
| 3 | done emits newline | |
| 4 | error prefix | |
