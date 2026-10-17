# Frozen Decision multimodal comparison

Follow-up LIBERO prompt/interface repairs and all version-specific results are
recorded in [LIBERO_REPAIR.md](LIBERO_REPAIR.md). The original50-episode result
remains unchanged. Latest paired variants have four tasks at5/5 joint; the
drawer-plus-bowl task remains2/5. The subsequent user-authorized LIBERO
multimodal comparison is documented in [LIBERO_MULTIMODAL.md](LIBERO_MULTIMODAL.md).

The2026-10-17 retest adds the verified native motion description, short Jev-style
XYZ questions, no outgoing camera K/T, target markers and a separate world-axis
compass condition. See [the fixed contract](LIBERO_MOTION_MULTIMODAL.md) and
[the results](LIBERO_MOTION_MM_RESULTS.md). These are separate versions and do
not overwrite the earlier comparison.

## Authorized experiment

1. Ten existing LIBERO-Plus Goal policies, five paired initial states each.
   Only replace Jev with `gpt-6-luna` Decisions. Preserve the per-task source
   commit, phase logic, processing, thresholds, original text and options.
   The actor receives no images. Task1202 remains an unstable reference.
2. Develop explicit task-specific plans/processing for the official GPT-6 Astra
   top five RoboDojo tasks. Freeze each version before its three-episode test.
   Record development failures separately; three successes are not a broad
   generalization claim.
3. Only after Phase2 passes, compare RGB addition and separate removals of
   processed evidence, three episodes per task per fixed condition.

The later direct instruction to test multimodality on LIBERO supersedes the
Phase2 prerequisite for this LIBERO comparison. It does not claim that all
five RoboDojo tasks passed.

Use only company-server-2 physical GPUs4–7. Preserve native evaluation rules.
Use local ChatGPT Pro `gpt-6.1-sol/high` for planning and iteration, and the
separately authorized du key for Luna. Never read or reuse caz/z credentials.
Experience is collected in English but not injected into either runtime model.

## Files

- `prepare_baselines.py`: reads the existing source-backed viewer metadata,
  verifies every Git source against its original SHA256, recovers original
  options and freezes the task-specific launcher command. No simulator/model.
- `legacy_decisions.py`: original state and Choice descriptions to Decisions;
  preserves actual returned choices/probabilities and rejects incomplete,
  refused, wrong-model, invalid or non-English text requests.
- `libero_entry.py`: installs the transport adapter before executing an
  unchanged frozen policy. No fallback to another model or to Jev.
- `run_libero_campaign.py`: foreground queue across GPUs4–7, paired initial
  states, unchanged frozen commands, disk guard, immutable per-episode manifests,
  provider failures and joint native/program terminal results. Resume skips
  completed episodes and refuses to replay an interrupted episode silently.

Every actual provider request/response is saved separately from the original
legacy request and its normalized result. A prepared request is not a received
answer. Phase1 does not add model instructions, images, memory or guessed
probabilities. Source hashes and original option manifests are audit evidence,
not model input. A failed run remains in the episode denominator; transport or
environment failures are also labeled independently.

At initial inspection the server's root and /data shared a volume with
approximately16GiB free. A later read-only check found115GiB free on that same
project volume; this agent deleted no existing assets. Runs can remain under
the new project worktree on this volume. Do not move bulk assets to another
mount without the required explicit confirmation. No driver or CUDA changes.

The old LIBERO policies use RGB-D for processing and local GroundingDINO/SAM
where specified; only their structured text reaches the Phase1 actor. Source
freezing covers181 files declared by the old archive plus150 lazy-import
dependencies from the same per-task Git commits (331 files total). The archive
omitted `libero_goal_static_vision.py`; the first deployment wave exposed this.
Task1202 also creates two sequential actor instances in one recorder, requiring
append-only shared request numbering. Neither fix changes the original policy.
The four deployment episodes remain saved separately from the complete-bundle
50-episode campaign, including its drawer success and three setup failures.
The50 episodes are
paired against previously used initial states, not unseen-state evaluation.
Task1202 is explicitly labeled an unstable development reference.
