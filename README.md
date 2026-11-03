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
2. three chains, concurrently, from different starting points: a draft, then full rewrites that see the photo and
   the module rendered from the judge's four views; a rejected module gets a repair call
3. pick one chain final with per-view questions in both seat orders
4. more full rewrites of the picked module
5. output (a measured fallback if nothing ever rendered)

Settings are in `src/settings.py`, prompts in `src/prompts/`, the helper library and framing appended to every
module in `src/prompts/helpers.js` and `src/prompts/frame.js`.
