# NOTE
- The `local.py` file contains the `httpx` library and is prohibited for submission. This file is intended solely for development purposes and must not be included when submitting your worker.
- Files not required when submitting a worker: `local.py`, `prompts.txt`, `README.md`, `TESTING.md`, `reports/`, `ai3d-devkit/`, `competition information/`.

# 3d-gen-api (round-3 leader base)

Earlier bases:
- the previous miner404-based code (`R3_PLAN`) is backed up in `outputs/backup-r3plan-2026-11-10/`;
- the c18 pipeline is commit 0efbf1c.

Entry point: `main.py` -> `async generate(image, seed, witness) -> str | None`. The pipeline runs in a worker thread.
`_Bridge` turns `witness.responses.create(...)` and `witness.render(...)` into blocking calls on the event loop.

## Layout

| File | Contents |
| --- | --- |
| `miner404/versions.py` | `ACTIVE_PLAN` (= `R4_PLAN`) and `LEADER_PLAN`, the leader's original |
| `miner404/pipeline.py` | Stages, budget reservations, request ids, the JS wrapper (fit, flat tilt, bake, grade), selection, pose, finishing passes |
| `miner404/prompts.py` | Every model text and JSON schema; `agents.md` is the output spec they embed; `*_NEUTRAL` are our neutral-light texts |
| `miner404/images.py` | Close-up of the photo, zoomed judge views, JPEG and data URLs |
| `miner404/orient.py` | Silhouette IoU yaw, stand-up variants for flat objects, turned modules |
| `miner404/tilt.py`, `measure_own.py` | The leader's 22° photo tilt and its photo mask (only when `photo_tilt` is on) |
| `miner404/match.py` | Pixel metrics against the photo, pose and grade search (used only in measured plans) |
| `miner404/budget.py`, `pricing.json` | Thread-safe credit and call ledger; reservations use the measured maximum output (`RESERVE_OUTPUT`) |
| `miner404/fallback.py` | A one-colour blob returned when no candidate validates |
| `local.py` | Development runner: real model calls, local renderer, cache; never part of a submission |

## Active plan (`R4_PLAN`)

1. **Drafts:** three `gpt-6.1-sol` high drafts (`plain`, `proportions`, `plain`; the leader has six).
   - Each draft gets the photo plus an object close-up.
   - A rejected module gets one Sol repair.
2. **Draft selection:** keep **1**.
   - Sol medium scores the candidates in both presentation orders, on the judge's four front views at 1024 px and the
     stage-2 grid in neutral light.
   - Lower is better: mean front penalty, +0.25 × grid, +2 when three side views look like garbage.
3. **Rewrites, 14 gated steps on one lineage** (the leader has 10).
   - Each step rewrites the module from the photo, the close-up, its zoomed views, its grid and its code.
   - A 2-call panel scores child and parent; the child is kept unless the parent leads by more than 0.25.
   - A step whose rewrite gave no module keeps the parent without a panel.
   - Models per step: Sol high, Astra high, Sol xhigh, Sol xhigh, Astra high, Sol xhigh, Astra high, Sol xhigh,
     Sol xhigh, Sol xhigh, then Sol high ×4.
   - Steps the budget can no longer reserve are skipped.
4. **Pose:** the quarter turn that best matches the photo silhouette, and for flat objects 45° and 90° stand-ups. The
   selector judges them against the incumbent; a new pose must win by 0.5.
5. **Finish (`outline_fit_last`):**
   - grade (identity), 15° tilt toward the cameras for flat objects;
   - bake every transform into the vertices, nested parts included;
   - fit to 0.99 of the unit cube;
   - the fit is dropped if it changes the views by more than 12.

**What `R4_PLAN` changes from the leader:**
- 3 drafts instead of 6, and 4 more Sol-high rewrite steps.
- No 22° photo tilt (`photo_tilt=False`).
- No `METAL_PASS` (`metal_pass=False`).
- Our neutral-light texts (`neutral_texts=True`): a metal recipe of metalness 0.85–1.0, no "lower the metalness" rewrite
  item, and no "turned black" selector flaw.
- No panel for a step whose rewrite gave no module (`skip_lonely_panel=True`).

Other plans:
- `R4_BASE_PLAN`: the same changes with the leader's 6 drafts and 10 steps.
- `R4_SOL_PLAN`: `R4_PLAN` with the Astra steps on Sol high and 16 steps.

**Budget:** each call's reservation uses the measured maximum output instead of the cap, with 6% of the 5M credits
kept back. A late step is skipped rather than overspent.
