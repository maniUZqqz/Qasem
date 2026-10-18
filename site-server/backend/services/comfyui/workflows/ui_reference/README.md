# UI-format reference workflows

These three files are the original ComfyUI **UI-format** exports (`nodes` array),
kept for reference. All three now exist in submittable **API format** one level up:

- `wan22_i2v.ui.json` → `../wan22_i2v_v1.json` (proven working on the prototype)
- `flux_txt2img.ui.json` → `../flux_txt2img_v1.json` (hand-converted 2026-08-27 —
  core nodes only: CheckpointLoader/CLIPTextEncode/EmptyLatent/KSampler/VAEDecode/SaveImage)
- `flux_img_edit.ui.json` → `../flux_img_edit_v1.json` (hand-converted 2026-08-27 —
  adds LoadImage/ImageScale/VAEEncode/FluxGuidance; cfg 1.0 + guidance 3.5, denoise patchable)

**If ComfyUI rejects a converted FLUX graph** (validation error on submit), the
authoritative fix is: open the UI file in ComfyUI → Dev mode → "Save (API Format)"
→ replace the corresponding `../flux_*_v1.json` (keep the manifest's patch points
in sync with the new node IDs).
