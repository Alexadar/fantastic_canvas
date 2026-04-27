# canvas_backend selftest

> scopes: kernel
> requires: `uv sync`
> out-of-scope: browser canvas UI (see canvas_webapp selftest)

Spatial discovery for canvas. Kernel-side only.

## Pre-flight

```bash
cd new_codebase
rm -rf .fantastic
```

## Tests

### Test 1: reflect

```bash
CB=$(uv run python kernel.py call core create_agent handler_module=canvas_backend.tools | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
uv run python kernel.py call $CB reflect | python -m json.tool | grep -F '"discover"'
```
Expected: `discover` present in `verbs`.

### Test 2: discover requires positive w, h

```bash
uv run python kernel.py call $CB discover x=0 y=0 w=0 h=0
```
Expected: `{"error":"…w and h required and > 0"}`.

### Test 3: discover finds intersecting agents

```bash
A=$(uv run python kernel.py call core create_agent handler_module=file.tools x=100 y=100 width=50 height=50 | python -c "import json,sys;print(json.load(sys.stdin)['id'])")
uv run python kernel.py call $CB discover x=0 y=0 w=200 h=200 | python -m json.tool | grep -F "\"id\": \"$A\""
```
Expected: matches (the file agent at (100,100) is in the search rect).

### Test 4: discover excludes self

```bash
uv run python kernel.py call $CB discover x=0 y=0 w=10000 h=10000 | python -m json.tool | grep -c "\"id\": \"$CB\""
```
Expected: 0.

## Cleanup

```bash
rm -rf .fantastic
```

## Summary

| # | Test | Pass |
|---|------|------|
| 1 | reflect lists verbs | |
| 2 | discover requires w,h > 0 | |
| 3 | discover finds intersecting | |
| 4 | discover excludes self | |
