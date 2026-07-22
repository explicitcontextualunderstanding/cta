# Agent Instructions

## Container Runtime: Apple Container (NOT Docker)

This project uses **Apple Container** (`container` CLI) exclusively for all
containerized test sessions. We do NOT use Docker.

- **CLI:** `container` (macOS-native, ships with macOS 15+)
- **Images:** `container image ls` (NOT `docker images`)
- **Run:** `container run` (NOT `docker run`)
- **List:** `container list --all` (shows stopped containers)
- **Registry:** `registry.rossollc.com/hermes:latest` (local, digest `59843a2193a4`)
- **System start:** `container system start` (required before first run)

### Why not Docker

Apple Container provides lightweight macOS-native micro-VMs (4 CPU, 2GB RAM)
without the Docker Desktop licensing requirement. All harness scripts
(`scripts/m3_interactive_harness.py`, `scripts/capture_harness.py`) invoke
`container run` directly.

### Known issue: kalloc.1024 kernel memory leak

Each container start/stop cycle leaks ~100k elements from `data.kalloc.1024`.
Threshold: 3M elements. Check headroom before launching:

```bash
zprint | grep "data.kalloc.1024"
```

If headroom < 200k elements, reboot before running captures. See
`docs/container_mounts_and_secrets.md` for the full persistence evolution
(M2 → M3 → P8) driven by this crash.

### Bind mounts (crash-safe persistence)

```
--mount type=bind,source=<host_path>,target=<container_path>
```

Key mounts:
- Workspace: `data/m3_captures/<run_id>/workspace/` → `/root/workspace`
- Hermes home: `data/m3_captures/<run_id>/hermes_home/` → `/home/hermes/.hermes`
- Output: `data/m3_captures/<run_id>/` → `/root/output`

### Secrets (env-var injection only)

Secrets are passed via `container run -e KEY=VALUE`. They exist only in the
VM's process environment — never written to disk inside the container.

| Secret | Host source | Env var |
|--------|-------------|---------|
| OpenCode Go API key | `~/.enclave/opencode_primary.txt` | `OPENCODE_GO_API_KEY` |
| Qoder PAT | `~/.enclave/qoder.txt` | `QODER_PERSONAL_ACCESS_TOKEN` |

## Friction guidance scope

Runtime friction detection (Plan 8) and the regime-response protocol in
SKILL.md v2.5.0 are scoped to the **qodercli skill only**. Do not extend
friction guidance to other skills until Gap 3 behavioral evidence closes
(±adaptation paired design proving CPI recovery).

## Commit discipline

- Capture evidence (classification.json, result.json, hermes_stdout.txt,
  run.sh, run_metadata.txt, git_diff.txt) IS committed.
- Heavy runtime artifacts (state.db, hermes_home/lsp/, hermes_home/bin/,
  logs, caches) are gitignored — they are recoverable from the container
  image, not evidence.
- Plans are living documents — update them as evidence accumulates.
