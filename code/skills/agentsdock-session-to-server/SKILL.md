---
name: agentsdock-session-to-server
description: Export one selected local Codex conversation and its AgentsDock timeline to an SSH server, register an independent idle AgentsDock chat, and verify native continuation. Use for one-way local-to-server session migration, including server02; does not synchronize future messages or migrate a project environment.
---

# Selected Codex conversation migration

Use `scripts/transfer_session.py`; it uses Python's standard library and SSH. Resolve the user's configured SSH Host alias. Read server-operator when available. Never transfer authentication, provider configuration, the whole sessions database, or unrelated chats.

## Workflow

1. Determine the exact selected conversation. `list` prints IDs and titles only. Default selection uses `CODEX_THREAD_ID`; reject ambiguous titles.
2. Confirm the existing remote project working directory. This migration transfers conversation history and chat attachments, not project source, environments, running processes, robot assets, or referenced external image files. Inspect the destination project separately and report any mismatch before treating it as ready to run.
3. Use the user's authorized remote asset mount for bundles and the AgentsDock event history. Native Codex rollouts must be regular files under the destination `.codex/sessions` directory. Obtain explicit confirmation for native home placement if this conflicts with the user's large-file mount rule; only then pass `--allow-native-home`.
4. Run `transfer`. It snapshots complete JSONL lines, checks SHA256, retains all native records including compactions, remaps execution cwd metadata, creates a clean chat using the live server API, installs its selected UI history and registered attachments, refreshes the event sequence cache using the per-chat history maintenance API, and calls `/codex/load` without sending a model prompt. Authentication is read privately from the destination's own AgentDock service environment file.
5. Verify the receipt, runtime result, idle state, and timeline in the destination UI. A successful HTTP response alone is not proof that the thread loaded. Check native thread ID/path and runtime status; never call turn/start as a migration test.
6. Give the destination chat title/ID and snapshot cutoff. The user opens that chat on server02 and sends the next message there. Later local messages are not synchronized. Explain that Codex resumes its normal compacted context while all raw history is retained; this does not put every historic token into the next context window.

Commands are single lines; replace explicit placeholders before running:

```bash
python3 ~/.codex/skills/agentsdock-session-to-server/scripts/transfer_session.py list
```

```bash
python3 ~/.codex/skills/agentsdock-session-to-server/scripts/transfer_session.py transfer --session '<exact-chat-ID-or-native-UUID>' --host server02 --remote-cwd /home/user/ykj/project/gpt6/jev-RSI --remote-root /data/ykj_robodojo/session_exports --allow-native-home
```

## Recovery and boundaries

- `manifest.json` records source IDs, checksums, record counts, path mapping and cutoff. `receipt.json` records the new destination chat and native path. Keep both with the bundle.
- Source files are read only. Destination existing threads or collisions are never overwritten. Do not delete a pre-existing thread to make a retry pass.
- Registration precedes native resume. If resume fails, use the receipt to inspect/retry `/codex/load`; do not rerun transfer to create duplicates. Re-importing a completed bundle is idempotent.
- UI history is staged only for the newly-created, still-idle chat. Its event directory and registered attachment data reside on the asset mount via directory symlinks; native rollouts stay regular files for AgentDock discovery. Remap the selected owner's nested file metadata so scoped downloads work. No global server settings are changed and no service restart is needed.
- Historical jobs, goals, queued actions, peer grants and active-run metadata are not activated. A local in-progress UI turn gets a clearly marked imported stop event. Historical filesystem links and remote-server handles can remain stale; they are evidence, not live resources.
- Preserve the destination's provider/authentication configuration. Never transfer local API keys or SSH keys. Keys previously written by the user inside the selected conversation remain part of that explicitly selected conversation; do not print raw history to terminal output.
- The native parser import endpoint has byte/message limits. This helper preserves the selected original AgentsDock event log instead of silently importing only its tail or changing the server's limits.
- Copying events alone leaves the live server's sequence cache stale. The helper appends an empty migration checkpoint and runs `/history/prune-duplicates` on this new chat, which removes the checkpoint, deduplicates previously imported display rows, and refreshes the sequence high-water mark. The untouched source event snapshot remains in the bundle. Verify strict monotonicity again after `/codex/load` appends native status events.
