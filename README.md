# Kinetica

**Professional motion graphics toolkit for Blender**

Kinetica brings 15 production-ready motion graphics presets directly into Blender's viewport sidebar. Select an object, click a preset, get a polished animation — every time. No keyframe juggling. No graph editor surgery. No fighting with rotation modes or shared materials.

[![Blender](https://img.shields.io/badge/Blender-3.x%20%7C%204.x%20%7C%205.x-orange)](https://www.blender.org/)
[![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey)]()
[![License](https://img.shields.io/badge/license-GPL--3.0-blue)]()

---

## Installation

1. Download the latest [**kinetica.zip**](../../releases/latest) from the Releases page
2. In Blender: `Edit → Preferences → Add-ons → Install…`
3. Select `kinetica.zip` (do **not** unzip first)
4. Enable **Kinetica**
5. Open the N-panel in the 3D Viewport → **Kinetica** tab

## What's inside

**Transparency**
- Fade In / Fade Out with driver-based material system
- Real-time duration adjustment

**Scale**
- Pop In · Pop Out · Bounce In · Squash & Stretch · Drop & Roll · Zoom Punch
- Safe positive-curve interpolation — never inverts normals or breaks mirrored objects

**Movement**
- Six-direction Move In / Move Out
- Adjustable distance and easing

**Rotation**
- One-shot rotations on any axis
- Custom turn count, clockwise or counter-clockwise
- Auto-converts glTF quaternion rotation to Euler

**Continuous Loops**
- Float · Spin · Wobble · Shake · Pulse · Swing
- Independent speed control via Loop Cycle
- Infinite cycling with fcurve modifiers

## Power features

**Stagger** — Multi-select N objects, set delay, click any preset → each object enters in sequence. Cinematic reveals in two clicks.

**Stack Mode** — Layer presets without erasing previous animation. Pop In at frame 1, Pop Out at frame 100 — both preserved.

**Auto Single-User** — Fading an object that shares a material? Kinetica detects it and creates a private copy automatically. No more "all my logos faded together" disasters.

**Delta-channel architecture** — Every preset uses `delta_location`, `delta_rotation_euler`, `delta_scale`. Your existing animation, NLA strips, and rigged actions stay untouched. Kinetica layers on top.

**One-click cleanup** — Remove Fade, Clear Transforms, or Clear EVERYTHING — exhaustive cleanup that restores nodes, drivers, keyframes, and original material settings.

## Compatibility

- Blender 3.x, 4.x, 5.x (including Blender 4.4+ Slotted Actions API)
- Windows, macOS, Linux
- All render engines (Eevee, Cycles, Workbench)
- Works on: Mesh, Curve, Empty, Armature, Camera, Light, Lattice, GPencil

## Quick usage

1. Set the timeline playhead to where the animation should start
2. Select one or more objects
3. Set **Duration** (or **Loop Cycle** for continuous effects)
4. Click any preset — done

## Author

Built by **Saeed Amani**

## License

GPL-3.0-or-later — see [LICENSE](LICENSE)
