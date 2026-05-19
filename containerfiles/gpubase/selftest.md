# containerfiles/gpubase selftest

> scopes: gpu-host, image, boot, http, ws, rest, canvas, add-member, install-bundle, persistence, shutdown
> requires: NVIDIA driver + nvidia-container-toolkit + CDI spec on the host (see ../gpubase/README.md "Host setup"); `podman` ≥ 4.x; outbound network; host port `18080` free

Mirrors `../base/selftest.md` 1:1 for probes 1–10. Only difference:
the `boot` probe gains a **`gpu-host`** sanity check that `nvidia-smi`
inside the container sees the GPU.

**Status: not yet executed.** Will be filled out the first time we
test on a real GPU host.

## Pre-flight (extra vs the slim selftest)

- `nvidia-smi` works on the host (driver loaded, GPU present).
- `ls /etc/cdi/nvidia.yaml` exists (`sudo nvidia-ctk cdi generate ...`
  was run).
- `podman run --rm --device nvidia.com/gpu=all nvidia/cuda:12.4.1-base-ubuntu24.04 nvidia-smi`
  succeeds from a throwaway container.

## Setup (delta vs slim)

```bash
WORKDIR=$(mktemp -d)
IMG=fantastic-canvas-gpubase:dev
./containerfiles/gpubase/build.sh
podman run -d --name ft-gpu \
  --device nvidia.com/gpu=all \
  -v "$WORKDIR:/workdir" \
  -p 18080:8080 \
  "$IMG"
# wait for [kernel] up (same loop as slim selftest)
```

## Probe 0 — `gpu-host` (extra)

```bash
podman exec ft-gpu nvidia-smi
```

Expected: prints GPU model + driver version + memory. **PASS** if the
GPU is listed.

Failure modes:
- "command not found": image doesn't have nvidia-smi → wrong base
  image (use `nvidia/cuda:*-runtime-*`, not `*-base-*`).
- "could not find …" / "No devices were found": CDI spec missing or
  `--device nvidia.com/gpu=all` flag not passed.

## Probes 1–10

Same as `../base/selftest.md`. Reuse those instructions verbatim,
substituting `ft-gpu` for `ft-test` and `fantastic-canvas-gpubase:dev`
for the image tag.

## Cleanup

```bash
podman stop ft-gpu
podman rm -f ft-gpu
rm -rf "$WORKDIR"
```

## Results table (TBD — populate on first GPU run)

| # | Probe | Scope | Pass/Fail | Notes |
|---|---|---|---|---|
| 0 | gpu-host | gpu-host | — | |
| 1 | image | image | — | |
| 2 | boot | boot | — | |
| 3 | http | http | — | |
| 4 | rest | rest | — | |
| 5 | ws | ws | — | |
| 6 | canvas | canvas | — | |
| 7 | add-member | add-member | — | |
| 8 | install-bundle | install-bundle | — | |
| 9 | persistence | persistence | — | |
| 10 | shutdown | shutdown | — | |
