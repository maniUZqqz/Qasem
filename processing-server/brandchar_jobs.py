#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Brand character studio on the GPU node (agent 2.27): job kind `brandchar.render` - an AI-illustrated / 3D-look variant of the
owner's code-drawn brand character, rendered by the node's own ComfyUI (FLUX image edit = img2img from the reference picture).

How the identity is kept: the site sends the code-drawn character (the pose the owner picked) as `reference.png` and a prompt built from the
locked character sheet. The graph is the node's own `flux-edit-*` profile (VAEEncode of the reference, `denoise` 0.5-0.65), so shapes
and colours of the reference survive; IP-Adapter / PuLID custom nodes are only *reported* (caps.brandchar.identity_tools) - the base path
needs nothing beyond what the owner already has (ComfyUI + FLUX). The site checks every result against the locked sheet afterwards.

Stdlib only (the agent is stdlib Python). The module never stops the agent: `register()` is called from one guarded line in agent.py.

    python brandchar_jobs.py --check      exit 0 when this node can run the job (ComfyUI profiles + a FLUX checkpoint file); used by requirements.d/brandchar.json
"""
import json
import os
import sys

VERSION = "1.0"
KIND = "brandchar.render"
KINDS = (KIND,)
HERE = os.path.dirname(os.path.abspath(__file__))
PREFERRED_PROFILES = ("flux-edit-balanced", "flux-edit-preserve")
TXT2IMG_PROFILES = ("flux-product-balanced", "flux-product-fast", "flux-product-portrait")
IDENTITY_NEEDLES = (("ipadapter", "ipadapter"), ("pulid", "pulid"))


def _profiles(agent=None):
    if agent is not None:
        try:
            return agent.load_profiles()
        except Exception:  # noqa: BLE001
            pass
    try:
        with open(os.path.join(HERE, "upmarket_comfyui_flask", "profiles.json"), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return []


def pick_profile(profiles, wanted="", has_reference=True):
    """The profile to run: the payload's own choice, else the first installed preferred one (edit with a reference, text-to-image without)."""
    by_id = {p.get("id"): p for p in profiles}
    if wanted and wanted in by_id:
        return by_id[wanted]
    order = PREFERRED_PROFILES if has_reference else TXT2IMG_PROFILES
    for pid in order:
        if pid in by_id:
            return by_id[pid]
    kind = "edit" if has_reference else "image"
    return next((p for p in profiles if p.get("kind") == kind), None)


def identity_tools(comfy_nodes):
    names = [str(n).lower() for n in (comfy_nodes or [])]
    return [key for key, needle in IDENTITY_NEEDLES if any(needle in n for n in names)]


def controls_from(payload, profile):
    """Only controls the profile really has; sane clamps (the site is trusted but a bad number must not crash ComfyUI)."""
    have = {c.get("name") for c in (profile or {}).get("controls", [])}
    out = {}

    def put(name, value, lo, hi, cast):
        if name in have and value is not None:
            try:
                out[name] = max(lo, min(hi, cast(value)))
            except (TypeError, ValueError):
                pass

    put("width", payload.get("width"), 512, 1536, int)
    put("height", payload.get("height"), 512, 1536, int)
    put("steps", payload.get("steps"), 4, 50, int)
    put("guidance", payload.get("guidance"), 1.0, 8.0, float)
    put("denoise", payload.get("denoise"), 0.2, 0.95, float)
    if "seed" in have:
        out["seed"] = int(payload.get("seed", -1)) if str(payload.get("seed", "")).lstrip("-").isdigit() else -1
    return out


def run(job, agent):
    p = job.payload or {}
    prompt = str(p.get("prompt") or "").strip()
    if not prompt:
        raise RuntimeError("brandchar.render: the prompt is empty")
    ref = p.get("reference") or ""
    has_ref = bool(ref and job.input_path(ref))
    profiles = _profiles(agent)
    profile = pick_profile(profiles, str(p.get("profile") or ""), has_ref)
    if profile is None:
        raise RuntimeError("no FLUX profile for ComfyUI is installed on this node (looked for %s)" % ", ".join(PREFERRED_PROFILES))
    image_name = None
    if has_ref and profile.get("kind") in ("edit", "video"):
        image_name = agent.comfy_upload("nm_bc_%s.png" % job.uid[:8], job.input_bytes(ref))
    controls = controls_from(p, profile)
    graph = agent.apply_profile(profile, prompt, str(p.get("negative_prompt") or ""), image_name, controls)
    job.progress(0.05, "brand character: %s (%s)" % (profile.get("id"), p.get("mode") or "illustrated"))
    _saved, primary = agent.comfy_run(graph, job)
    return {"primary": primary, "engine": "comfyui", "profile": profile.get("id"), "identity": "img2img" if image_name else "text",
            "identity_tools": identity_tools(getattr(agent, "CAPS_COMFY_NODES", None) or []), "seed": controls.get("seed")}


def caps(agent):
    """Heartbeat facts: is the job runnable here, and which identity tools exist."""
    profiles = _profiles(agent)
    ok = any(p.get("id") in PREFERRED_PROFILES for p in profiles)
    nodes = []
    try:
        nodes = list(agent.CAPABILITIES_CACHE.get("comfy_nodes") or [])
    except Exception:  # noqa: BLE001
        pass
    return {"brandchar": {"version": VERSION, "ready": bool(ok), "profiles": [p.get("id") for p in profiles if "flux" in str(p.get("id"))], "identity_tools": identity_tools(nodes)}}


def register(agent, handlers):
    """Called once from agent.py: adds the handler and the heartbeat facts. A broken module must never stop the agent."""
    handlers[KIND] = lambda job, _a=agent: run(job, _a)
    orig = agent.Capabilities.probe
    if not getattr(orig, "_brandchar", False):
        def probe(self):
            out = orig(self)
            try:
                nodes = out.get("comfy_nodes") or []
                c = caps(agent)
                c["brandchar"]["identity_tools"] = identity_tools(nodes)
                out.update(c)
            except Exception as e:  # noqa: BLE001 - never let this keep the heartbeat from going out
                out["brandchar"] = {"version": VERSION, "ready": False, "error": str(e)[:160]}
            return out

        probe._brandchar = True
        agent.Capabilities.probe = probe
    return True


def _flux_checkpoint_present():
    """A FLUX checkpoint file anywhere under a ComfyUI `models/` folder next to the node (portable layout) or the one named by NM_COMFYUI_DIR."""
    roots = []
    env = os.environ.get("NM_COMFYUI_DIR")
    if env:
        roots.append(env)
    here = HERE
    for _ in range(5):
        here = os.path.dirname(here)
        for name in ("ComfyUI_windows_portable", "ComfyUI"):
            roots.append(os.path.join(here, name))
    for root in roots:
        for base in (os.path.join(root, "ComfyUI", "models"), os.path.join(root, "models")):
            if not os.path.isdir(base):
                continue
            for sub in ("checkpoints", "unet", "diffusion_models"):
                d = os.path.join(base, sub)
                if os.path.isdir(d) and any("flux" in f.lower() and f.lower().endswith((".safetensors", ".gguf", ".sft")) for f in os.listdir(d)):
                    return True
    return False


def check():
    profiles = _profiles()
    if not any(p.get("id") in PREFERRED_PROFILES for p in profiles):
        print("no flux-edit profile in upmarket_comfyui_flask/profiles.json")
        return 1
    if not _flux_checkpoint_present():
        print("no FLUX checkpoint was found next to ComfyUI (set NM_COMFYUI_DIR if ComfyUI lives elsewhere)")
        return 2
    print("brandchar ready: FLUX profiles + checkpoint found")
    return 0


if __name__ == "__main__":
    sys.exit(check() if "--check" in sys.argv else 0)
