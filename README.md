# 3d-phase2-api-DuongND

Turns one product photo into a deterministic Three.js module with OpenAI models, for the image-to-Three.js
competition. `main.py` exposes the runtime entry point:

```python
async def generate(image: bytes, seed: int, witness) -> str | None
```

Every model call goes through `witness.responses.create(request_id=...)` and every preview through
`witness.render(...)`, so a run can be recorded and replayed: request ids and every decision depend only on recorded
responses and renders, never on clocks or completion order.

## Pipeline (`src/pipeline.py`)

1. plan: notes on the photo and a short checklist
2. three chains, concurrently, from different starting points: a high-effort draft, then full rewrites that see the
   photo, a close-up crop of the object and the module rendered from the judge's four views; a rejected module gets
   a repair call
3. pick one chain final: one call scores them all from their four-view sheets, in both candidate orders. Every
   judging call (this pick, the re-pick of each wide pass, the final check and the pose check) runs on gpt-6-luna,
   whose verdicts agree best with GLM's
4. three wide passes on the picked module: three rewrites at once (plain, proportions and silhouette, details and
   colours), then the same pick over the current module and its rewrites, the current one with a 0.25 bonus so a
   rewrite replaces it only when clearly better; a pass narrows to fewer rewrites (down to the plain single rewrite)
   when the budget cannot hold them plus the final check. Then one check: the picked module against the result in
   the judge's Stage 1 (per view, both seat orders); the picked one comes back only when it wins
5. pose: extra tilts towards the camera, screened by how well their colour layout matches the photo (no model
   call), and kept only when they win the same Stage-1 check
6. output: a flat object tipped 25° towards the camera, every part's transform baked into its geometry and the tight
   box fitted to the cube (a measured fallback if nothing ever rendered)

Settings are in `src/settings.py`, prompts in `src/prompts/`, the helper library and framing appended to every
module in `src/prompts/helpers.js` and `src/prompts/frame.js`.

## Branch `round3-wide`: Luna judges and the 25° flat tilt

These two changes come on top of the wide post-pick passes (c7fbf6e).

**1. Every judging role runs on Luna** (`src/settings.py`).
- The roles:
  - `pick` (the chain pick and the re-pick of each wide pass) uses `gpt-6-luna` medium;
  - `duel` (final check, pose check) and `orient` use `gpt-6-luna` low;
  - all of them use `service_tier` "default".
- Why: of the OpenAI models, Luna's verdicts agree best with the judge's GLM. This has been verified repeatedly, and mdt's L133 found that the official Stage-1 prompt on Luna low matched GLM best of 8 configurations. It also costs 1/20 of Sol.
- The rewrites and the drafts stay on Sol. `critic` stays on Sol too; it is unused (`review=False`).

**2. Flat objects are tipped 25°, not 15°.**
- Changed in `tiltTowardCamera` in `src/prompts/frame.js`. Playbook item 2, `coder_system.md` and `module.py` now say 25° as well.
- **Why.** A 15° tilt makes a flat top exactly edge-on to the judge's `front_below` camera, which sits 15° below the front.
  - Round-2 official data for this repo's entry (df5beaf) shows the cost. The 15° tilt fired on 24 of 128 prompts, and on those:
    - the `front_below` penalty was 1.6 worse than the leader's and 1.3 worse than miner404's;
    - the results were 7-12-5 against the leader and 1-14-9 against miner404.
  - On the other 104 prompts, the net per prompt was +0.17 against the leader and −0.11 against miner404.
- **GLM test.** Setup:
  - the official round-2 modules of those 24 prompts, with only the tilt constant changed;
  - judge-box 0.1.3 on an A100-PCIE-40GB (driver 610.57.04), batch-invariant, smoke test 3/3, seed 3347385824.

  Result: **25° beat 15° 11-7-6 (margin +0.167)**. The 30° and 0° runs were still running when this was written.
- The pose step's extra tilts (+10°/+20°) now come on top of 25°.

These changes pass the offline smoke test: fake replies and renders, a deterministic replay, and the judging calls on Luna. They have not yet been run end to end with real models.
