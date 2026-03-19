# emptydir

![vibe coded](https://img.shields.io/badge/vibe-coded-ff69b4)
![python 3](https://img.shields.io/badge/python-3-3776AB)
![heresy: 2/10](https://img.shields.io/badge/heresy-2%2F10-blueviolet)

dekube transform that auto-detects shared `emptyDir` volumes between init/sidecar/main containers and replaces anonymous Compose volumes with shared named volumes.

> Heresy level: 2/10 — rewrites volume entries behind the scenes, but only does what Kubernetes already does natively. Invisible fix for an invisible gap.

## Why

In Kubernetes, `emptyDir` volumes are pod-scoped — all containers in the pod (init, main, sidecar) see the same filesystem. A common pattern: an init container populates a Java truststore, the main container reads it.

dekube-engine converts `emptyDir` mounts to anonymous Compose volumes (just the mount path). But anonymous volumes are per-service in Compose — each container gets its own empty directory. The init container writes into the void; the main container sees nothing.

## What it does

1. Scans K8s manifests for `emptyDir` volumes mounted by 2+ containers in the same pod
2. Identifies which Compose services correspond to those containers (by naming convention)
3. Replaces anonymous volume entries with a shared named volume (`{workload}-{vol_name}`)
4. Declares the named volume via `ctx.compose_extras` for the top-level `volumes:` section

Runs at priority 1000 — before bitnami (1500) and fix-permissions (8000), so downstream transforms see the corrected volume layout.

Every shared volume is logged to stderr for transparency.

## Install

Built into the helmfile2compose distribution — no install needed.

Standalone: `python3 dekube-manager.py emptydir`
