# `file` bundle — filesystem root as an agent

One agent per filesystem root. Core holds no filesystem code; all file
ops go through a `file` agent via `agent_call`.

## Add a root

```
add file name=project                          # empty root → project_dir
add file name=sandbox root=/tmp/agent-sandbox
add file name=readonly_view root=. readonly=true
add file name=docs root=. hidden=["drafts", ".fantastic"]
```

Quickstart provisions a default `file_project` (root=`""` → project_dir)
so `file_project_<hex>` is available immediately on fresh projects.

## Verbs (via `agent_call`)

```
# tree of the root (or a subdir)
@file_<id> agent_call verb=list path=""

# read text or image file (image → base64)
@file_<id> agent_call verb=read path=CLAUDE.md

# write text file (refused when readonly=true)
@file_<id> agent_call verb=write path=notes.md content="hello"

# delete / rename / mkdir (also refused when readonly=true)
@file_<id> agent_call verb=delete path=notes.md
@file_<id> agent_call verb=rename old_path=a.txt new_path=b.txt
@file_<id> agent_call verb=mkdir path=new_dir/sub
```

## Metadata (agent.json fields)

| field | meaning |
|---|---|
| `root` | absolute path. Empty = project_dir. |
| `readonly` | bool. When true, write/delete/rename/mkdir return `{"error":"readonly"}`. |
| `hidden` | list of directory/file names to skip in `list`. Default: `__pycache__`, `.git`, `node_modules`, `.fantastic`, etc. |

## Path safety

Every verb resolves `root/path` via `Path.resolve()` then checks it is
still under `root`; escapes return `{"error": "path outside root: ..."}`.

## Notes

- Multiple roots coexist as independent agents. Policy (readonly, hidden)
  is per-agent, not global.
- Binary writes not supported. Image reads return `{kind:"image",
  image_base64, mime}`.
- Directory deletion not supported; use `mkdir` + `rename` as needed.
