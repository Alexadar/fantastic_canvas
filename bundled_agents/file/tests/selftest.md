# `file` bundle self-test

Scope: one bundle. Drive via CLI or WS. No AI provider needed.

## Pre-flight

```
add file name=project          # root="" → project_dir
add file name=ro root=. readonly=true
```

Capture ids with `list_agents` filtered by `bundle=="file"`. Call them
`FILE_PROJECT` and `FILE_RO`.

## Tests

### F1 — list (tree, hidden excluded)
```
@FILE_PROJECT agent_call verb=list path=""
```
Expected: `{files: [...]}`. `.fantastic`, `.git`, `node_modules` absent.

### F2 — list subdir
```
@FILE_PROJECT agent_call verb=list path=core
```
Expected: tree under `core/`.

### F3 — read text
```
@FILE_PROJECT agent_call verb=read path=CLAUDE.md
```
Expected: `{path, content}` with `# Fantastic Canvas` near the top.

### F4 — read image (base64)
If `bundled_agents/canvas/web/public/` has any image file, read it.
Expected: `{kind: "image", image_base64, mime}`.

### F5 — read missing
```
@FILE_PROJECT agent_call verb=read path=nope.md
```
Expected: `{error: "not found: nope.md"}`.

### F6 — write then read round-trip
```
@FILE_PROJECT agent_call verb=write path=_ft_smoke.txt content="hi"
@FILE_PROJECT agent_call verb=read  path=_ft_smoke.txt
```
Expected: content = "hi". Clean up:
```
@FILE_PROJECT agent_call verb=delete path=_ft_smoke.txt
```

### F7 — mkdir then rename
```
@FILE_PROJECT agent_call verb=mkdir  path=_ft_dir
@FILE_PROJECT agent_call verb=write  path=_ft_dir/a.txt content="x"
@FILE_PROJECT agent_call verb=rename old_path=_ft_dir/a.txt new_path=_ft_dir/b.txt
@FILE_PROJECT agent_call verb=read   path=_ft_dir/b.txt
@FILE_PROJECT agent_call verb=delete path=_ft_dir/b.txt
```
Expected: reads succeed; `a.txt` gone, `b.txt` present, content preserved.
(Directory cleanup is out of scope — there's no `rmdir` verb on purpose.)

### F8 — readonly refuses mutations
```
@FILE_RO agent_call verb=write  path=x.txt content="nope"
@FILE_RO agent_call verb=delete path=CLAUDE.md
@FILE_RO agent_call verb=rename old_path=a new_path=b
@FILE_RO agent_call verb=mkdir  path=x
```
Expected: each returns `{error: "readonly"}`. File tree unchanged.

### F9 — readonly still allows reads
```
@FILE_RO agent_call verb=list path=""
@FILE_RO agent_call verb=read path=CLAUDE.md
```
Expected: both succeed normally.

### F10 — path-escape rejected
```
@FILE_RO agent_call verb=read  path=../../etc/passwd
@FILE_RO agent_call verb=write path=../../outside.txt content="x"
```
Expected: both return `{error: "path outside root: ..."}`. Nothing
written outside `root`.

## Pass matrix

| # | Test | Pass |
|---|---|---|
| F1 | list tree | |
| F2 | list subdir | |
| F3 | read text | |
| F4 | read image | |
| F5 | read missing | |
| F6 | write round-trip | |
| F7 | mkdir + rename | |
| F8 | readonly refuses mutations | |
| F9 | readonly allows reads | |
| F10 | path escape rejected | |
