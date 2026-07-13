# =====================================================================
# Kinetica  v7.8  —  Professional Motion Graphics Toolkit
# Author: Saeed Amani
# =====================================================================
# Blender 3.x / 4.x / 5.x compatible (Slotted Actions supported)
# Presets: Fade, Pop, Bounce, Squash, Move, Rotate, Float, Spin,
#          Wobble, Shake + real-time duration + one-click cleanup.
# =====================================================================

bl_info = {
    "name": "Kinetica",
    "author": "Saeed Amani",
    "version": (7, 12, 0),
    "blender": (3, 0, 0),
    "location": "View3D > Sidebar > Kinetica",
    "description": "Kinetica — Professional motion graphics toolkit by Saeed Amani",
    "warning": "",
    "category": "Animation",
}

import bpy
import math
from bpy.types import Panel, Operator, PropertyGroup
from bpy.props import (IntProperty, BoolProperty, FloatProperty,
                       EnumProperty, StringProperty, PointerProperty)

# ═════════ Constants ═════════
PROP       = "auto_fade_alpha"
PROP_START = "_fade_start"
PROP_END   = "_fade_end"
MIX_NAME   = "Auto_Fade_Mix"
TRAN_NAME  = "Auto_Fade_Transparent"
VALID      = {'MESH', 'CURVE', 'SURFACE', 'META', 'FONT', 'VOLUME'}
IS_4X      = bpy.app.version >= (4, 0, 0)
EULER_MODES = {'XYZ', 'XZY', 'YXZ', 'YZX', 'ZXY', 'ZYX'}


def _is_mirrored(obj):
    """True if object has any negative scale axis. delta_scale must stay
    POSITIVE always (it's a pure scale factor); for mirrored objects we
    additionally avoid overshoot easing because BACK can briefly send
    delta_scale below zero, which combined with the negative base flips
    the visible mirror state. See Pop presets."""
    bx, by, bz = obj.scale
    return bx < 0 or by < 0 or bz < 0


def _ensure_euler_mode(obj):
    """Rotation presets animate `delta_rotation_euler`, which does not
    evaluate correctly when the object's `rotation_mode` is QUATERNION
    or AXIS_ANGLE (common after glTF/glb import). Switch to XYZ.
    Blender preserves the visual rotation when converting.
    Returns True if the mode was changed."""
    if obj.rotation_mode not in EULER_MODES:
        obj.rotation_mode = 'XYZ'
        return True
    return False


def _xform_objs(context):
    """Return every selected object that supports transforms (any type
    except strange non-transform ones). Empties, Armatures, Cameras,
    Lights, Lattices, GPencil — all welcome for transform presets."""
    return [o for o in context.selected_objects
            if o is not None and hasattr(o, 'delta_location')]

_ORIG_KEYS = (
    "_fade_orig_blend_method", "_fade_orig_shadow_method",
    "_fade_orig_surface_render", "_fade_orig_overlap", "_fade_orig_shadow",
)

DIR_VEC = {
    'UP':    (0, 0,  1),
    'DOWN':  (0, 0, -1),
    'LEFT':  (-1, 0, 0),
    'RIGHT': ( 1, 0, 0),
    'FRONT': (0, -1, 0),
    'BACK':  (0,  1, 0),
}


# ═════════ FCurve compatibility (Blender 3.x / 4.x / 5.x) ═════════
def _iter_fcurves(action):
    """Yield fcurves from legacy OR slotted action (Blender 4.4+)."""
    if action is None:
        return
    # Legacy API
    fcs = getattr(action, 'fcurves', None)
    if fcs is not None:
        try:
            for fc in fcs:
                yield fc
            return
        except Exception:
            pass
    # Slotted API — try collection style
    try:
        for layer in getattr(action, 'layers', []) or []:
            for strip in getattr(layer, 'strips', []) or []:
                bags = getattr(strip, 'channelbags', None)
                if bags is not None:
                    try:
                        for bag in bags:
                            for fc in getattr(bag, 'fcurves', []) or []:
                                yield fc
                        continue
                    except Exception:
                        pass
                # Fallback — channelbag() method with slots
                cb_method = getattr(strip, 'channelbag', None)
                if cb_method is not None and callable(cb_method):
                    try:
                        for slot in getattr(action, 'slots', []) or []:
                            bag = cb_method(slot)
                            if bag is not None:
                                for fc in getattr(bag, 'fcurves', []) or []:
                                    yield fc
                    except Exception:
                        pass
    except Exception:
        pass


def _remove_fcurve(action, fc):
    """Remove a specific fcurve — works on legacy or slotted actions."""
    # Legacy
    legacy = getattr(action, 'fcurves', None)
    if legacy is not None:
        try:
            if fc in list(legacy):
                legacy.remove(fc)
                return True
        except Exception:
            pass
    # Slotted
    try:
        for layer in getattr(action, 'layers', []) or []:
            for strip in getattr(layer, 'strips', []) or []:
                bags = getattr(strip, 'channelbags', None) or []
                for bag in bags:
                    bag_fcs = getattr(bag, 'fcurves', None)
                    if bag_fcs is None:
                        continue
                    try:
                        if fc in list(bag_fcs):
                            bag_fcs.remove(fc)
                            return True
                    except Exception:
                        continue
    except Exception:
        pass
    return False


def _action_empty(action):
    for _ in _iter_fcurves(action):
        return False
    return True


# ═════════ Fade-specific FCurve helpers ═════════
def _fade_fcurve(obj):
    if obj.animation_data is None or obj.animation_data.action is None:
        return None
    for fc in _iter_fcurves(obj.animation_data.action):
        if PROP in fc.data_path:
            return fc
    return None


def _move_end_keyframe(obj, new_end):
    fc = _fade_fcurve(obj)
    if fc is None or len(fc.keyframe_points) < 2:
        return False
    max_i = 0
    for i in range(1, len(fc.keyframe_points)):
        if fc.keyframe_points[i].co.x > fc.keyframe_points[max_i].co.x:
            max_i = i
    kp = fc.keyframe_points[max_i]
    kp.co.x           = float(new_end)
    kp.handle_left.x  = float(new_end)
    kp.handle_right.x = float(new_end)
    fc.update()
    return True


def _delete_fade_fcurve(obj):
    if obj.animation_data is None or obj.animation_data.action is None:
        return False
    action = obj.animation_data.action
    to_del = [fc for fc in _iter_fcurves(action) if PROP in fc.data_path]
    if not to_del:
        return False
    for fc in to_del:
        _remove_fcurve(action, fc)
    if _action_empty(action):
        obj.animation_data_clear()
    return True


# ═════════ Generic keyframe helpers ═════════
def _set_kp_interp(obj, data_path, interp, easing='AUTO'):
    if obj.animation_data is None or obj.animation_data.action is None:
        return
    for fc in _iter_fcurves(obj.animation_data.action):
        if fc.data_path != data_path:
            continue
        for kp in fc.keyframe_points:
            kp.interpolation = interp
            kp.easing = easing
        fc.update()


def _add_cycles_mod(obj, data_path):
    if obj.animation_data is None or obj.animation_data.action is None:
        return
    for fc in _iter_fcurves(obj.animation_data.action):
        if fc.data_path != data_path:
            continue
        if any(m.type == 'CYCLES' for m in fc.modifiers):
            continue
        mod = fc.modifiers.new(type='CYCLES')
        mod.mode_before = 'REPEAT'
        mod.mode_after  = 'REPEAT'
        fc.update()


def _clear_keyframes_by_path(obj, data_paths):
    if obj.animation_data is None or obj.animation_data.action is None:
        return False
    if isinstance(data_paths, str):
        data_paths = {data_paths}
    else:
        data_paths = set(data_paths)
    action = obj.animation_data.action
    to_del = [fc for fc in _iter_fcurves(action) if fc.data_path in data_paths]
    removed = False
    for fc in to_del:
        if _remove_fcurve(action, fc):
            removed = True
    if _action_empty(action):
        obj.animation_data_clear()
    return removed


def _clear_kf_in_range(obj, data_path, f_start, f_end):
    """Remove keyframes on data_path within [f_start, f_end] inclusive.
    Keyframes outside the range are preserved → enables preset stacking."""
    if obj.animation_data is None or obj.animation_data.action is None:
        return False
    removed = False
    for fc in _iter_fcurves(obj.animation_data.action):
        if fc.data_path != data_path:
            continue
        targets = [kp for kp in fc.keyframe_points
                   if f_start <= kp.co.x <= f_end]
        for kp in targets:
            try:
                fc.keyframe_points.remove(kp)
                removed = True
            except Exception:
                pass
        fc.update()
    return removed


def _strip_loop_modifiers(obj, data_path):
    """Remove CYCLES/NOISE fcurve modifiers on data_path.
    Called before a one-shot preset so it isn't wrecked by leftover loops."""
    if obj.animation_data is None or obj.animation_data.action is None:
        return
    for fc in _iter_fcurves(obj.animation_data.action):
        if fc.data_path != data_path:
            continue
        for m in list(fc.modifiers):
            if m.type in {'CYCLES', 'NOISE'}:
                try:
                    fc.modifiers.remove(m)
                except Exception:
                    pass
        fc.update()


def _prep_channel(obj, data_path, f0, f1, stack):
    """Prepare a channel for a one-shot preset: range-clear if stacking,
    full-clear otherwise. Always strips conflicting loop modifiers."""
    if stack:
        _clear_kf_in_range(obj, data_path, f0, f1)
        _strip_loop_modifiers(obj, data_path)
    else:
        _clear_keyframes_by_path(obj, {data_path})


# ═════════ Material helpers (fade) ═════════
def _save_mat_settings(mat):
    if any(k in mat for k in _ORIG_KEYS):
        return
    if IS_4X:
        mat["_fade_orig_surface_render"] = getattr(mat, "surface_render_method", "DITHERED")
        mat["_fade_orig_overlap"]        = int(getattr(mat, "use_transparency_overlap", False))
        mat["_fade_orig_shadow"]         = int(getattr(mat, "use_transparent_shadow",   False))
    else:
        mat["_fade_orig_blend_method"]  = getattr(mat, "blend_method",  "OPAQUE")
        mat["_fade_orig_shadow_method"] = getattr(mat, "shadow_method", "OPAQUE")


def _apply_mat_settings(mat, props):
    if IS_4X:
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method = 'BLENDED'
        if hasattr(mat, "use_transparency_overlap"):
            mat.use_transparency_overlap = props.use_transparency_overlap
        if hasattr(mat, "use_transparent_shadow"):
            mat.use_transparent_shadow = props.use_transparent_shadows
    else:
        if hasattr(mat, "blend_method"):
            mat.blend_method = 'BLEND'
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = 'NONE' if not props.use_transparent_shadows else 'HASHED'


def _restore_mat_settings(mat):
    if IS_4X:
        if hasattr(mat, "surface_render_method"):
            mat.surface_render_method    = mat.pop("_fade_orig_surface_render", "DITHERED")
        if hasattr(mat, "use_transparency_overlap"):
            mat.use_transparency_overlap = bool(mat.pop("_fade_orig_overlap", 0))
        if hasattr(mat, "use_transparent_shadow"):
            mat.use_transparent_shadow   = bool(mat.pop("_fade_orig_shadow",  0))
    else:
        if hasattr(mat, "blend_method"):
            mat.blend_method  = mat.pop("_fade_orig_blend_method",  "OPAQUE")
        if hasattr(mat, "shadow_method"):
            mat.shadow_method = mat.pop("_fade_orig_shadow_method", "OPAQUE")
    for k in _ORIG_KEYS:
        if k in mat:
            del mat[k]


# ═════════ Node helpers (fade) ═════════
def _mat_output(tree):
    for n in tree.nodes:
        if n.type == 'OUTPUT_MATERIAL':
            return n
    return None


def _ensure_fade_nodes(tree, mat_output):
    nodes, links = tree.nodes, tree.links
    mix = nodes.get(MIX_NAME)
    if mix:
        return mix
    surf = mat_output.inputs.get('Surface')
    if surf is None:
        return None
    orig = surf.links[0].from_socket if surf.is_linked else None
    mix = nodes.new('ShaderNodeMixShader')
    mix.name  = MIX_NAME
    mix.label = "Auto Fade Mix"
    mix.location = (mat_output.location.x - 320, mat_output.location.y)
    tr = nodes.new('ShaderNodeBsdfTransparent')
    tr.name  = TRAN_NAME
    tr.label = "Auto Fade Transparent"
    tr.location = (mix.location.x - 240, mix.location.y - 140)
    links.new(tr.outputs['BSDF'], mix.inputs[1])
    if orig:
        links.new(orig, mix.inputs[2])
    links.new(mix.outputs['Shader'], surf)
    return mix


def _add_driver(mix, obj):
    try:
        mix.inputs[0].driver_remove("default_value")
    except Exception:
        pass
    fc = mix.inputs[0].driver_add("default_value")
    d = fc.driver
    d.type = 'SCRIPTED'
    v = d.variables.new()
    v.name = "a"
    v.type = 'SINGLE_PROP'
    t = v.targets[0]
    t.id_type   = 'OBJECT'
    t.id        = obj
    t.data_path = f'["{PROP}"]'
    d.expression = "a"
    fc.update()


def _init_prop(obj, value=1.0):
    obj[PROP] = float(value)
    try:
        obj.id_properties_ui(PROP).update(
            min=0.0, max=1.0, soft_min=0.0, soft_max=1.0)
    except Exception:
        pass


# ═════════ Real-time update callbacks ═════════
def _update_duration(self, context):
    new_dur = self.fade_duration
    for obj in bpy.data.objects:
        if PROP not in obj or PROP_START not in obj:
            continue
        start   = int(obj[PROP_START])
        new_end = start + new_dur
        if _move_end_keyframe(obj, new_end):
            obj[PROP_END] = new_end
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type in {'VIEW_3D', 'DOPESHEET_EDITOR',
                             'GRAPH_EDITOR', 'NLA_EDITOR', 'TIMELINE'}:
                area.tag_redraw()


def _update_mat_settings(self, context):
    for obj in bpy.data.objects:
        if PROP not in obj:
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or not mat.use_nodes:
                continue
            tree = mat.node_tree
            if tree and tree.nodes.get(MIX_NAME):
                _apply_mat_settings(mat, self)


# ═════════ Properties ═════════
class AutoFadeProperties(PropertyGroup):
    fade_duration: IntProperty(
        name="Duration",
        description="Animation duration in frames (fade is real-time)",
        default=15, min=1, max=500,
        update=_update_duration,
    )
    loop_cycle: IntProperty(
        name="Loop Cycle",
        description="Frames per ONE full cycle of Float / Spin / Wobble (lower = faster)",
        default=90, min=4, max=2000, soft_min=10, soft_max=240,
    )
    use_transparent_shadows: BoolProperty(
        name="Transparent Shadows", default=False,
        update=_update_mat_settings,
    )
    use_transparency_overlap: BoolProperty(
        name="Transparency Overlap", default=False,
        description="OFF = cleaner result",
        update=_update_mat_settings,
    )
    direction: EnumProperty(
        name="Direction",
        items=[
            ('UP',    "Up",    "From/to top",    'TRIA_UP',        0),
            ('DOWN',  "Down",  "From/to bottom", 'TRIA_DOWN',      1),
            ('LEFT',  "Left",  "From/to left",   'TRIA_LEFT',      2),
            ('RIGHT', "Right", "From/to right",  'TRIA_RIGHT',     3),
            ('FRONT', "Front", "From/to front",  'AXIS_FRONT',     4),
            ('BACK',  "Back",  "From/to back",   'AXIS_TOP',       5),
        ],
        default='UP',
    )
    rotation_axis: EnumProperty(
        name="Axis",
        items=[
            ('X', "X", "X axis"),
            ('Y', "Y", "Y axis"),
            ('Z', "Z", "Z axis (vertical)"),
        ],
        default='Z',
    )
    turns: FloatProperty(
        name="Turns", default=1.0, min=0.1, max=20.0,
        description="Number of full rotations",
    )
    reverse_rotation: BoolProperty(
        name="Reverse (CCW)",
        description="Reverse direction — counter-clockwise when viewed from the positive side of the chosen axis",
        default=False,
    )
    distance: FloatProperty(
        name="Distance", default=2.0, min=0.01, max=100.0,
        unit='LENGTH',
        description="Offset distance / bounce height",
    )
    amplitude: FloatProperty(
        name="Amplitude", default=0.3, min=0.01, max=10.0,
        description="Loop amplitude (height or angle in radians)",
    )
    shake_strength: FloatProperty(
        name="Shake Strength", default=0.15, min=0.01, max=5.0,
    )
    stagger_step: IntProperty(
        name="Stagger",
        description="Frames of delay between each selected object (0 = all start together). The active object goes first",
        default=0, min=0, max=500,
    )
    stack_mode: BoolProperty(
        name="Stack Effects",
        description="ON: preserve keyframes outside the new preset's frame range (combine effects naturally). OFF: clear the channel before applying",
        default=True,
    )
    overshoot: BoolProperty(
        name="Overshoot (bouncy)", default=True,
        description="Pop In with overshoot for bouncy feel",
    )


# ═════════ Fade apply/remove ═════════
def apply_fade(obj, frame_start, duration, fade_in, props):
    if not obj.material_slots:
        return 0
    val_a = 0.0 if fade_in else 1.0
    val_b = 1.0 if fade_in else 0.0
    frame_end = frame_start + duration
    _init_prop(obj, val_a)
    count = 0
    for slot in obj.material_slots:
        mat = slot.material
        if mat is None:
            continue

        # ── Single-user: if this material is shared with other objects,
        # make a private copy for THIS object so the driver only affects it.
        # Skip if already faded (already private) — detected by Mix node.
        already_private = (mat.use_nodes and mat.node_tree and
                           mat.node_tree.nodes.get(MIX_NAME) is not None)
        if not already_private and mat.users > 1:
            new_mat = mat.copy()
            new_mat.name = f"{mat.name}_{obj.name}"
            slot.material = new_mat
            mat = new_mat

        mat.use_nodes = True
        tree = mat.node_tree
        if tree is None:
            continue
        out = _mat_output(tree)
        if out is None:
            continue
        mix = _ensure_fade_nodes(tree, out)
        if mix is None:
            continue
        _add_driver(mix, obj)
        _save_mat_settings(mat)
        _apply_mat_settings(mat, props)
        count += 1
    if count == 0:
        return 0

    dp = f'["{PROP}"]'
    obj[PROP] = val_a
    obj.keyframe_insert(data_path=dp, frame=int(frame_start))
    obj[PROP] = val_b
    obj.keyframe_insert(data_path=dp, frame=int(frame_end))
    fc = _fade_fcurve(obj)
    if fc:
        for kp in fc.keyframe_points:
            kp.interpolation = 'LINEAR'
        fc.update()
    obj[PROP_START] = int(frame_start)
    obj[PROP_END]   = int(frame_end)
    bpy.context.view_layer.update()
    return count


def remove_fade(obj):
    removed = False
    # Only mesh-like objects have material_slots
    if hasattr(obj, 'material_slots'):
        for slot in obj.material_slots:
            mat = slot.material
            if mat is None or not mat.use_nodes:
                continue
            tree = mat.node_tree
            if tree is None:
                continue
            mix = tree.nodes.get(MIX_NAME)
            if mix:
                try:
                    mix.inputs[0].driver_remove("default_value")
                except Exception:
                    pass
                try:
                    orig = (mix.inputs[2].links[0].from_socket
                            if mix.inputs[2].is_linked else None)
                    out = _mat_output(tree)
                    if out and orig:
                        surf = out.inputs.get('Surface')
                        if surf:
                            tree.links.new(orig, surf)
                except Exception:
                    pass
                tr = tree.nodes.get(TRAN_NAME)
                if tr:
                    tree.nodes.remove(tr)
                tree.nodes.remove(mix)
                removed = True
            _restore_mat_settings(mat)
    if _delete_fade_fcurve(obj):
        removed = True
    for key in (PROP, PROP_START, PROP_END):
        if key in obj:
            del obj[key]
            removed = True
    bpy.context.view_layer.update()
    return 1 if removed else 0


def _eval_alpha(obj, context):
    try:
        dg = context.evaluated_depsgraph_get()
        return float(obj.evaluated_get(dg).get(PROP, obj.get(PROP, 1.0)))
    except Exception:
        return float(obj.get(PROP, 1.0))


# ═════════ Transform presets (use DELTA transforms) ═════════
def _preset_pop_in(obj, f0, f1, overshoot=True, stack=True):
    """Pop In implemented WITHOUT BACK easing.

    BACK easing causes 'anticipation undershoot' — the curve dips BELOW
    the source value at frame f0 before launching. With source ≈ 0, this
    means delta_scale momentarily goes NEGATIVE, which (a) flips normals
    via backface culling, and (b) inverts mirrored objects. The visible
    artifact: object briefly appears flipped at the start of Pop In.

    Solution: build the bouncy feel from explicit keyframes that NEVER
    cross zero. Pop In curve: 0.01 → 1.15 (overshoot) → 1.0 (settle).
    Without overshoot: simple 0.01 → 1.0 with smooth ease-out.
    """
    _prep_channel(obj, 'delta_scale', f0, f1, stack)
    eps = 0.01
    span = max(2, f1 - f0)

    if overshoot:
        # Three-keyframe bounce: small → overshoot above 1 → settle at 1
        peak_frame = f0 + int(span * 0.75)   # 75% of duration
        obj.delta_scale = (eps, eps, eps)
        obj.keyframe_insert('delta_scale', frame=f0)
        obj.delta_scale = (1.15, 1.15, 1.15)
        obj.keyframe_insert('delta_scale', frame=peak_frame)
        obj.delta_scale = (1.0, 1.0, 1.0)
        obj.keyframe_insert('delta_scale', frame=f1)
        # CUBIC easing — never undershoots, just smooth Bezier-ish curve
        _set_kp_interp(obj, 'delta_scale', 'CUBIC', 'EASE_OUT')
    else:
        obj.delta_scale = (eps, eps, eps)
        obj.keyframe_insert('delta_scale', frame=f0)
        obj.delta_scale = (1.0, 1.0, 1.0)
        obj.keyframe_insert('delta_scale', frame=f1)
        _set_kp_interp(obj, 'delta_scale', 'CUBIC', 'EASE_OUT')


def _preset_pop_out(obj, f0, f1, stack=True):
    """Pop Out implemented WITHOUT BACK easing — same reasoning as Pop In.

    BACK EASE_IN would overshoot ABOVE the source (delta > 1) which is
    safe, but at the END can briefly dip below the destination (~0.01),
    sending delta below zero on overshoot frames. Use CUBIC instead.
    """
    _prep_channel(obj, 'delta_scale', f0, f1, stack)
    eps = 0.01
    obj.delta_scale = (1.0, 1.0, 1.0)
    obj.keyframe_insert('delta_scale', frame=f0)
    obj.delta_scale = (eps, eps, eps)
    obj.keyframe_insert('delta_scale', frame=f1)
    _set_kp_interp(obj, 'delta_scale', 'CUBIC', 'EASE_IN')


def _preset_squash_stretch(obj, f0, f1, stack=True):
    _prep_channel(obj, 'delta_scale', f0, f1, stack)
    mid = (f0 + f1) // 2
    obj.delta_scale = (1.0, 1.0, 1.0)
    obj.keyframe_insert('delta_scale', frame=f0)
    obj.delta_scale = (1.3, 1.3, 0.55)
    obj.keyframe_insert('delta_scale', frame=mid)
    obj.delta_scale = (1.0, 1.0, 1.0)
    obj.keyframe_insert('delta_scale', frame=f1)
    _set_kp_interp(obj, 'delta_scale', 'BEZIER', 'AUTO')


def _preset_bounce_in(obj, f0, f1, height, stack=True):
    _prep_channel(obj, 'delta_location', f0, f1, stack)
    obj.delta_location = (0, 0, height)
    obj.keyframe_insert('delta_location', frame=f0)
    obj.delta_location = (0, 0, 0)
    obj.keyframe_insert('delta_location', frame=f1)
    _set_kp_interp(obj, 'delta_location', 'BOUNCE', 'EASE_OUT')


def _preset_move_in(obj, f0, f1, direction, distance, stack=True):
    _prep_channel(obj, 'delta_location', f0, f1, stack)
    v = DIR_VEC[direction]
    obj.delta_location = (v[0]*distance, v[1]*distance, v[2]*distance)
    obj.keyframe_insert('delta_location', frame=f0)
    obj.delta_location = (0, 0, 0)
    obj.keyframe_insert('delta_location', frame=f1)
    _set_kp_interp(obj, 'delta_location', 'CUBIC', 'EASE_OUT')


def _preset_move_out(obj, f0, f1, direction, distance, stack=True):
    _prep_channel(obj, 'delta_location', f0, f1, stack)
    v = DIR_VEC[direction]
    obj.delta_location = (0, 0, 0)
    obj.keyframe_insert('delta_location', frame=f0)
    obj.delta_location = (v[0]*distance, v[1]*distance, v[2]*distance)
    obj.keyframe_insert('delta_location', frame=f1)
    _set_kp_interp(obj, 'delta_location', 'CUBIC', 'EASE_IN')


def _preset_rotate(obj, f0, f1, axis, turns, stack=True, ccw=False):
    _ensure_euler_mode(obj)
    _prep_channel(obj, 'delta_rotation_euler', f0, f1, stack)
    # For stacked rotation, use the current delta as starting point if a kp exists at f0
    if stack and obj.animation_data and obj.animation_data.action:
        # Find value right before f0 to start from (avoid jumps)
        for fc in _iter_fcurves(obj.animation_data.action):
            if fc.data_path == 'delta_rotation_euler':
                fc.update()
    obj.delta_rotation_euler = (0, 0, 0)
    obj.keyframe_insert('delta_rotation_euler', frame=f0)
    rot = [0, 0, 0]
    amount = 2 * math.pi * turns
    if ccw:
        amount = -amount
    rot['XYZ'.index(axis)] = amount
    obj.delta_rotation_euler = tuple(rot)
    obj.keyframe_insert('delta_rotation_euler', frame=f1)
    _set_kp_interp(obj, 'delta_rotation_euler', 'CUBIC', 'EASE_IN_OUT')


def _preset_float(obj, f0, duration, amplitude):
    _clear_keyframes_by_path(obj, {'delta_location'})
    f1  = f0 + duration
    mid = f0 + duration // 2
    obj.delta_location = (0, 0, 0)
    obj.keyframe_insert('delta_location', frame=f0)
    obj.delta_location = (0, 0, amplitude)
    obj.keyframe_insert('delta_location', frame=mid)
    obj.delta_location = (0, 0, 0)
    obj.keyframe_insert('delta_location', frame=f1)
    _set_kp_interp(obj, 'delta_location', 'BEZIER', 'AUTO')
    _add_cycles_mod(obj, 'delta_location')


def _preset_spin(obj, f0, duration, axis, ccw=False):
    _ensure_euler_mode(obj)
    _clear_keyframes_by_path(obj, {'delta_rotation_euler'})
    f1 = f0 + duration
    obj.delta_rotation_euler = (0, 0, 0)
    obj.keyframe_insert('delta_rotation_euler', frame=f0)
    rot = [0, 0, 0]
    amount = 2 * math.pi
    if ccw:
        amount = -amount
    rot['XYZ'.index(axis)] = amount
    obj.delta_rotation_euler = tuple(rot)
    obj.keyframe_insert('delta_rotation_euler', frame=f1)
    _set_kp_interp(obj, 'delta_rotation_euler', 'LINEAR', 'AUTO')
    _add_cycles_mod(obj, 'delta_rotation_euler')


def _preset_wobble(obj, f0, duration, amplitude):
    _ensure_euler_mode(obj)
    _clear_keyframes_by_path(obj, {'delta_rotation_euler'})
    q  = max(1, duration // 4)
    f1 = f0 + duration
    obj.delta_rotation_euler = (0, 0, 0)
    obj.keyframe_insert('delta_rotation_euler', frame=f0)
    obj.delta_rotation_euler = (0, amplitude, 0)
    obj.keyframe_insert('delta_rotation_euler', frame=f0 + q)
    obj.delta_rotation_euler = (0, 0, 0)
    obj.keyframe_insert('delta_rotation_euler', frame=f0 + 2*q)
    obj.delta_rotation_euler = (0, -amplitude, 0)
    obj.keyframe_insert('delta_rotation_euler', frame=f0 + 3*q)
    obj.delta_rotation_euler = (0, 0, 0)
    obj.keyframe_insert('delta_rotation_euler', frame=f1)
    _set_kp_interp(obj, 'delta_rotation_euler', 'BEZIER', 'AUTO')
    _add_cycles_mod(obj, 'delta_rotation_euler')


def _preset_shake(obj, f0, duration, strength):
    _clear_keyframes_by_path(obj, {'delta_location'})
    f1 = f0 + duration
    obj.delta_location = (0, 0, 0)
    obj.keyframe_insert('delta_location', frame=f0)
    obj.keyframe_insert('delta_location', frame=f1)
    if obj.animation_data and obj.animation_data.action:
        for fc in _iter_fcurves(obj.animation_data.action):
            if fc.data_path != 'delta_location':
                continue
            for m in list(fc.modifiers):
                if m.type == 'NOISE':
                    fc.modifiers.remove(m)
            mod = fc.modifiers.new(type='NOISE')
            mod.scale = 2.0
            mod.strength = strength
            try:
                mod.use_restricted_range = True
                mod.frame_start = f0
                mod.frame_end   = f1
            except Exception:
                pass
            fc.update()


def _preset_drop_roll(obj, f0, f1, height, stack=True):
    """Drop from above + roll on Y-axis as it lands."""
    _ensure_euler_mode(obj)
    _prep_channel(obj, 'delta_location', f0, f1, stack)
    _prep_channel(obj, 'delta_rotation_euler', f0, f1, stack)

    obj.delta_location = (0, 0, height)
    obj.keyframe_insert('delta_location', frame=f0)
    obj.delta_location = (0, 0, 0)
    obj.keyframe_insert('delta_location', frame=f1)
    _set_kp_interp(obj, 'delta_location', 'BOUNCE', 'EASE_OUT')

    obj.delta_rotation_euler = (0, 0, 0)
    obj.keyframe_insert('delta_rotation_euler', frame=f0)
    obj.delta_rotation_euler = (0, -math.pi, 0)   # one half-roll
    obj.keyframe_insert('delta_rotation_euler', frame=f1)
    _set_kp_interp(obj, 'delta_rotation_euler', 'CUBIC', 'EASE_OUT')


def _preset_pulse(obj, f0, duration, amplitude):
    """Continuous scale pulse (heartbeat-like) — uses delta_scale + CYCLES."""
    _clear_keyframes_by_path(obj, {'delta_scale'})
    f1  = f0 + duration
    mid = f0 + duration // 2
    pulse_factor = 1.0 + amplitude  # amplitude=0.15 → pulses to 1.15
    obj.delta_scale = (1.0, 1.0, 1.0)
    obj.keyframe_insert('delta_scale', frame=f0)
    obj.delta_scale = (pulse_factor, pulse_factor, pulse_factor)
    obj.keyframe_insert('delta_scale', frame=mid)
    obj.delta_scale = (1.0, 1.0, 1.0)
    obj.keyframe_insert('delta_scale', frame=f1)
    _set_kp_interp(obj, 'delta_scale', 'BEZIER', 'AUTO')
    _add_cycles_mod(obj, 'delta_scale')


def _preset_swing(obj, f0, duration, amplitude, axis):
    """Pendulum sway — continuous rotation oscillation on chosen axis."""
    _ensure_euler_mode(obj)
    _clear_keyframes_by_path(obj, {'delta_rotation_euler'})
    q  = max(1, duration // 4)
    f1 = f0 + duration
    ai = 'XYZ'.index(axis)

    def _set(angle, frame):
        rot = [0, 0, 0]
        rot[ai] = angle
        obj.delta_rotation_euler = tuple(rot)
        obj.keyframe_insert('delta_rotation_euler', frame=frame)

    _set(0,          f0)
    _set( amplitude, f0 + q)
    _set(0,          f0 + 2*q)
    _set(-amplitude, f0 + 3*q)
    _set(0,          f1)
    _set_kp_interp(obj, 'delta_rotation_euler', 'BEZIER', 'AUTO')
    _add_cycles_mod(obj, 'delta_rotation_euler')


def _preset_zoom_punch(obj, f0, f1, stack=True):
    """Sharp scale-up then ease back (button-press feel).
    Uses CUBIC easing throughout — BACK could undershoot below 1.0 at the
    end, which is still positive but visually jarring. CUBIC is crisp."""
    _prep_channel(obj, 'delta_scale', f0, f1, stack)
    mid = f0 + max(1, (f1 - f0) // 3)   # punch peak at 1/3 of range
    obj.delta_scale = (1.0, 1.0, 1.0)
    obj.keyframe_insert('delta_scale', frame=f0)
    obj.delta_scale = (1.4, 1.4, 1.4)
    obj.keyframe_insert('delta_scale', frame=mid)
    obj.delta_scale = (1.0, 1.0, 1.0)
    obj.keyframe_insert('delta_scale', frame=f1)
    _set_kp_interp(obj, 'delta_scale', 'CUBIC', 'EASE_OUT')


# ═════════ Cleanup helpers ═════════
def clear_transforms(obj):
    paths = {'delta_location', 'delta_rotation_euler', 'delta_scale',
             'location', 'rotation_euler', 'rotation_quaternion', 'scale'}
    cleared = _clear_keyframes_by_path(obj, paths)
    try:
        obj.delta_location = (0, 0, 0)
        obj.delta_rotation_euler = (0, 0, 0)
        obj.delta_scale = (1, 1, 1)
    except Exception:
        pass
    return cleared


def clear_all_animation(obj):
    had_fade  = remove_fade(obj) > 0
    had_xform = clear_transforms(obj)
    # Hard reset any remaining animation
    if obj.animation_data:
        try:
            obj.animation_data_clear()
        except Exception:
            pass
    return had_fade or had_xform


# ═════════ Operators ═════════
class KINETICA_OT_FadeIn(Operator):
    bl_idname = "kinetica.fade_in"
    bl_label  = "Fade In"
    bl_description = "Fade In: transparent → visible"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.kinetica_props
        frame = context.scene.frame_current
        objs  = [o for o in context.selected_objects if o.type in VALID]
        if not objs:
            self.report({'WARNING'}, "No valid objects selected.")
            return {'CANCELLED'}
        total = sum(apply_fade(o, frame, props.fade_duration, True, props) for o in objs)
        if total:
            f_end = frame + props.fade_duration
            self.report({'INFO'},
                f"Fade In | {len(objs)} obj, {total} mat | "
                f"{frame}→{f_end}  (object visible from frame {f_end})")
        else:
            self.report({'WARNING'}, "No materials found.")
        return {'FINISHED'}


class KINETICA_OT_FadeOut(Operator):
    bl_idname = "kinetica.fade_out"
    bl_label  = "Fade Out"
    bl_description = "Fade Out: visible → transparent"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.kinetica_props
        frame = context.scene.frame_current
        objs  = [o for o in context.selected_objects if o.type in VALID]
        if not objs:
            self.report({'WARNING'}, "No valid objects selected.")
            return {'CANCELLED'}
        total = sum(apply_fade(o, frame, props.fade_duration, False, props) for o in objs)
        if total:
            self.report({'INFO'},
                f"Fade Out | {len(objs)} obj, {total} mat | "
                f"{frame}→{frame+props.fade_duration}  (object hidden after frame {frame+props.fade_duration})")
        else:
            self.report({'WARNING'}, "No materials found.")
        return {'FINISHED'}


class KINETICA_OT_RemoveFade(Operator):
    bl_idname = "kinetica.remove_fade"
    bl_label  = "Remove Fade"
    bl_description = "Remove fade nodes, drivers, and ALL fade keyframes"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = [o for o in context.selected_objects if o.type in VALID]
        if not objs:
            self.report({'WARNING'}, "No objects selected.")
            return {'CANCELLED'}
        total = sum(remove_fade(o) for o in objs)
        if total:
            self.report({'INFO'}, f"Fade removed from {len(objs)} object(s).")
        else:
            self.report({'WARNING'}, "No fade to remove.")
        return {'FINISHED'}


class KINETICA_OT_RefreshDrivers(Operator):
    bl_idname = "kinetica.refresh_drivers"
    bl_label  = "Refresh Drivers"
    bl_description = "Re-attach drivers to newly added material slots"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        props = context.scene.kinetica_props
        objs  = [o for o in context.selected_objects
                 if o.type in VALID and PROP in o]
        if not objs:
            self.report({'WARNING'}, "No faded objects selected.")
            return {'CANCELLED'}
        total = 0
        for obj in objs:
            for slot in obj.material_slots:
                mat = slot.material
                if mat is None:
                    continue
                # Single-user shared materials (same logic as apply_fade)
                already_private = (mat.use_nodes and mat.node_tree and
                                   mat.node_tree.nodes.get(MIX_NAME) is not None)
                if not already_private and mat.users > 1:
                    new_mat = mat.copy()
                    new_mat.name = f"{mat.name}_{obj.name}"
                    slot.material = new_mat
                    mat = new_mat
                mat.use_nodes = True
                tree = mat.node_tree
                if tree is None:
                    continue
                out = _mat_output(tree)
                if out is None:
                    continue
                mix = _ensure_fade_nodes(tree, out)
                if mix is None:
                    continue
                _add_driver(mix, obj)
                _save_mat_settings(mat)
                _apply_mat_settings(mat, props)
                total += 1
        self.report({'INFO'}, f"Refreshed {total} material(s).")
        return {'FINISHED'}


_PRESET_DESC = {
    'POP_IN':     "Scale from 0 to full — bouncy pop-in",
    'POP_OUT':    "Scale from full to 0 — vanish effect",
    'SQUASH':     "Squash & Stretch — classic in-place bounce",
    'BOUNCE_IN':  "Drop from above with bouncy landing",
    'MOVE_IN':    "Slide in from chosen direction",
    'MOVE_OUT':   "Slide out to chosen direction",
    'ROTATE':     "One-shot rotation on chosen axis",
    'FLOAT':      "Continuous up/down float loop",
    'SPIN':       "Continuous spin loop on chosen axis",
    'WOBBLE':     "Continuous side-to-side sway",
    'SHAKE':      "Shake effect via noise modifier",
    'DROP_ROLL':  "Drop from above + roll as it lands",
    'PULSE':      "Continuous scale pulse (heartbeat)",
    'SWING':      "Continuous pendulum sway on chosen axis",
    'ZOOM_PUNCH': "Sharp scale punch then ease back (button press)",
}


class KINETICA_OT_ApplyPreset(Operator):
    """Apply a motion graphics preset to selected objects"""
    bl_idname = "kinetica.apply_preset"
    bl_label  = "Apply Preset"
    bl_options = {'REGISTER', 'UNDO'}

    preset: StringProperty()

    @classmethod
    def description(cls, context, properties):
        return _PRESET_DESC.get(properties.preset, "Apply preset")

    def execute(self, context):
        props = context.scene.kinetica_props
        frame = context.scene.frame_current
        duration = props.fade_duration
        objs = _xform_objs(context)
        if not objs:
            self.report({'WARNING'},
                "No objects selected. Select at least one object (mesh, empty, etc.).")
            return {'CANCELLED'}

        # Sort so the active object goes first (stagger feels natural this way),
        # then the rest in the order Blender returns them.
        active = context.active_object
        if active in objs:
            objs = [active] + [o for o in objs if o is not active]

        # Diagnostic: warn about constraints/locks that may block rotation
        if self.preset in {'ROTATE', 'SPIN', 'WOBBLE', 'SWING', 'DROP_ROLL'}:
            problems = []
            for obj in objs:
                if obj.constraints:
                    blocking = [c.name for c in obj.constraints
                                if c.type in {'LIMIT_ROTATION', 'COPY_ROTATION',
                                              'TRACK_TO', 'LOCKED_TRACK',
                                              'DAMPED_TRACK'}
                                and not c.mute]
                    if blocking:
                        problems.append(f"{obj.name}: {', '.join(blocking)}")
                if any(obj.lock_rotation):
                    problems.append(f"{obj.name}: rotation channel locked")
            if problems:
                msg = "Rotation may be blocked on: " + " | ".join(problems[:3])
                self.report({'WARNING'}, msg)

        # Pre-apply: track which objects will need rotation_mode switched
        switched_mode = []
        if self.preset in {'ROTATE', 'SPIN', 'WOBBLE', 'SWING', 'DROP_ROLL'}:
            for obj in objs:
                if obj.rotation_mode not in EULER_MODES:
                    switched_mode.append(obj.name)

        stagger = props.stagger_step
        for i, obj in enumerate(objs):
            f0 = frame + (i * stagger)
            f1 = f0 + duration
            try:
                self._apply(obj, props, f0, f1, duration)
            except Exception as e:
                self.report({'WARNING'}, f"Error on {obj.name}: {e}")

        if switched_mode:
            self.report({'INFO'},
                f"Switched rotation_mode → XYZ on: {', '.join(switched_mode[:3])}")

        # Build accurate range string per preset
        last_f0 = frame + (len(objs) - 1) * stagger
        if self.preset in {'FLOAT', 'SPIN', 'WOBBLE', 'PULSE', 'SWING'}:
            rng_end = last_f0 + props.loop_cycle
            rng = f"{frame}→{rng_end}  (cycle {props.loop_cycle}f, loops)"
        elif self.preset == 'SHAKE':
            rng = f"{frame}→{last_f0 + duration}  (shake)"
        else:
            rng = f"{frame}→{last_f0 + duration}"
        if stagger and len(objs) > 1:
            rng += f"  | stagger {stagger}f × {len(objs)} objs"
        self.report({'INFO'},
            f"{self.preset} | {len(objs)} object(s) | {rng}")
        return {'FINISHED'}

    def _apply(self, obj, props, f0, f1, duration):
        p = self.preset
        s = props.stack_mode
        if   p == 'POP_IN':     _preset_pop_in(obj, f0, f1, overshoot=props.overshoot, stack=s)
        elif p == 'POP_OUT':    _preset_pop_out(obj, f0, f1, stack=s)
        elif p == 'SQUASH':     _preset_squash_stretch(obj, f0, f1, stack=s)
        elif p == 'BOUNCE_IN':  _preset_bounce_in(obj, f0, f1, props.distance, stack=s)
        elif p == 'MOVE_IN':    _preset_move_in(obj, f0, f1, props.direction, props.distance, stack=s)
        elif p == 'MOVE_OUT':   _preset_move_out(obj, f0, f1, props.direction, props.distance, stack=s)
        elif p == 'ROTATE':     _preset_rotate(obj, f0, f1, props.rotation_axis, props.turns, stack=s, ccw=props.reverse_rotation)
        elif p == 'FLOAT':      _preset_float(obj, f0, props.loop_cycle, props.amplitude)
        elif p == 'SPIN':       _preset_spin(obj, f0, props.loop_cycle, props.rotation_axis, ccw=props.reverse_rotation)
        elif p == 'WOBBLE':     _preset_wobble(obj, f0, props.loop_cycle, props.amplitude)
        elif p == 'SHAKE':      _preset_shake(obj, f0, duration, props.shake_strength)
        elif p == 'DROP_ROLL':  _preset_drop_roll(obj, f0, f1, props.distance, stack=s)
        elif p == 'PULSE':      _preset_pulse(obj, f0, props.loop_cycle, props.amplitude)
        elif p == 'SWING':      _preset_swing(obj, f0, props.loop_cycle, props.amplitude, props.rotation_axis)
        elif p == 'ZOOM_PUNCH': _preset_zoom_punch(obj, f0, f1, stack=s)


class KINETICA_OT_ClearTransforms(Operator):
    bl_idname = "kinetica.clear_transforms"
    bl_label  = "Clear Transform Animation"
    bl_description = "Clear all transform keyframes (keeps fade)"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = _xform_objs(context)
        if not objs:
            self.report({'WARNING'}, "No objects selected.")
            return {'CANCELLED'}
        total = sum(1 for o in objs if clear_transforms(o))
        self.report({'INFO'}, f"Cleared transforms on {total}/{len(objs)} object(s).")
        return {'FINISHED'}


class KINETICA_OT_ClearAll(Operator):
    bl_idname = "kinetica.clear_all"
    bl_label  = "Clear ALL Animation"
    bl_description = "Remove ALL animation (fade + transforms) from selected objects"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = _xform_objs(context)
        if not objs:
            self.report({'WARNING'}, "No objects selected.")
            return {'CANCELLED'}
        total = sum(1 for o in objs if clear_all_animation(o))
        self.report({'INFO'}, f"Cleared everything on {total}/{len(objs)} object(s).")
        return {'FINISHED'}


# ═════════ Panels ═════════
class KINETICA_PT_Main(Panel):
    bl_label       = "Kinetica"
    bl_idname      = "KINETICA_PT_main"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Kinetica"

    def draw(self, context):
        layout = self.layout
        props  = context.scene.kinetica_props
        box = layout.box()
        col = box.column(align=True)
        col.label(text="Settings", icon='SETTINGS')
        col.prop(props, "fade_duration", slider=True)

        row = col.row(align=True)
        row.scale_y = 1.1
        icon = 'LAYER_USED' if props.stack_mode else 'LAYER_ACTIVE'
        row.prop(props, "stack_mode",
                 text="Stack Effects  (combine with previous)",
                 icon=icon, toggle=True)

        col.label(text=f"Current Frame:  {context.scene.frame_current}", icon='TIME')

        # Stagger — applies to all transform presets when multi-selecting
        sel_count = len([o for o in context.selected_objects
                         if hasattr(o, 'delta_location')])
        if sel_count > 1:
            col.separator(factor=0.3)
            col.prop(props, "stagger_step",
                     text=f"Stagger Delay  ({sel_count} objs)", slider=True)
            if props.stagger_step > 0:
                col.label(
                    text=f"Total span: {props.stagger_step * (sel_count - 1)}f",
                    icon='SEQUENCE')

        sel_faded = [o for o in context.selected_objects
                     if o.type in VALID and PROP_START in o]
        if sel_faded:
            s = int(sel_faded[0].get(PROP_START, 0))
            col.label(text=f"Fade Range:  {s} → {s + props.fade_duration}",
                      icon='ARROW_LEFTRIGHT')


class KINETICA_PT_Fade(Panel):
    bl_parent_id   = "KINETICA_PT_main"
    bl_label       = "Transparency / Fade"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Kinetica"

    def draw(self, context):
        layout = self.layout
        props  = context.scene.kinetica_props
        col = layout.column(align=True)
        col.label(text="Material  (real-time)", icon='MATERIAL')
        col.prop(props, "use_transparent_shadows",
                 text="Transparent Shadows", toggle=True)
        col.prop(props, "use_transparency_overlap",
                 text="Transparency Overlap", toggle=True)
        layout.separator(factor=0.3)
        row = layout.row(align=True)
        row.scale_y = 1.5
        row.operator("kinetica.fade_in",  text="Fade In",  icon='TRIA_RIGHT')
        row.operator("kinetica.fade_out", text="Fade Out", icon='TRIA_LEFT')


class KINETICA_PT_Scale(Panel):
    bl_parent_id   = "KINETICA_PT_main"
    bl_label       = "Scale  ·  Pop / Bounce / Squash"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Kinetica"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props  = context.scene.kinetica_props
        layout.prop(props, "overshoot")
        col = layout.column(align=True)
        row = col.row(align=True); row.scale_y = 1.4
        op = row.operator("kinetica.apply_preset", text="Pop In",  icon='ZOOM_IN')
        op.preset = 'POP_IN'
        op = row.operator("kinetica.apply_preset", text="Pop Out", icon='ZOOM_OUT')
        op.preset = 'POP_OUT'
        row = col.row(align=True); row.scale_y = 1.4
        op = row.operator("kinetica.apply_preset", text="Bounce In", icon='IPO_BOUNCE')
        op.preset = 'BOUNCE_IN'
        op = row.operator("kinetica.apply_preset", text="Squash",    icon='MOD_SIMPLEDEFORM')
        op.preset = 'SQUASH'
        row = col.row(align=True); row.scale_y = 1.4
        op = row.operator("kinetica.apply_preset", text="Drop & Roll", icon='PHYSICS')
        op.preset = 'DROP_ROLL'
        op = row.operator("kinetica.apply_preset", text="Zoom Punch",  icon='PROP_ON')
        op.preset = 'ZOOM_PUNCH'
        layout.separator(factor=0.3)
        layout.prop(props, "distance", text="Bounce / Drop Height")


class KINETICA_PT_Move(Panel):
    bl_parent_id   = "KINETICA_PT_main"
    bl_label       = "Move  ·  Directional Entry / Exit"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Kinetica"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props  = context.scene.kinetica_props
        layout.prop(props, "direction")
        layout.prop(props, "distance")
        row = layout.row(align=True); row.scale_y = 1.4
        op = row.operator("kinetica.apply_preset", text="Move In",  icon='FORWARD')
        op.preset = 'MOVE_IN'
        op = row.operator("kinetica.apply_preset", text="Move Out", icon='BACK')
        op.preset = 'MOVE_OUT'


class KINETICA_PT_Rotate(Panel):
    bl_parent_id   = "KINETICA_PT_main"
    bl_label       = "Rotation"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Kinetica"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props  = context.scene.kinetica_props
        row = layout.row()
        row.prop(props, "rotation_axis", expand=True)
        layout.prop(props, "turns")
        layout.prop(props, "reverse_rotation", icon='LOOP_BACK')
        row = layout.row(align=True); row.scale_y = 1.4
        op = row.operator("kinetica.apply_preset", text="Rotate", icon='FILE_REFRESH')
        op.preset = 'ROTATE'


class KINETICA_PT_Loops(Panel):
    bl_parent_id   = "KINETICA_PT_main"
    bl_label       = "Continuous Loops  (Float / Spin / Wobble / Shake)"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Kinetica"
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        props  = context.scene.kinetica_props
        col = layout.column(align=True)
        col.prop(props, "loop_cycle", slider=True)
        col.label(text=f"= {props.loop_cycle} frames per full cycle", icon='PREVIEW_RANGE')
        layout.prop(props, "amplitude")
        row = layout.row(align=True)
        row.label(text="Axis:")
        row.prop(props, "rotation_axis", expand=True)
        layout.prop(props, "reverse_rotation", icon='LOOP_BACK',
                    text="Reverse Spin Direction")
        col = layout.column(align=True)
        row = col.row(align=True); row.scale_y = 1.35
        op = row.operator("kinetica.apply_preset", text="Float", icon='ANCHOR_TOP')
        op.preset = 'FLOAT'
        op = row.operator("kinetica.apply_preset", text="Spin",  icon='FILE_REFRESH')
        op.preset = 'SPIN'
        row = col.row(align=True); row.scale_y = 1.35
        op = row.operator("kinetica.apply_preset", text="Wobble", icon='IPO_SINE')
        op.preset = 'WOBBLE'
        op = row.operator("kinetica.apply_preset", text="Shake",  icon='IPO_ELASTIC')
        op.preset = 'SHAKE'
        row = col.row(align=True); row.scale_y = 1.35
        op = row.operator("kinetica.apply_preset", text="Pulse",  icon='FORCE_HARMONIC')
        op.preset = 'PULSE'
        op = row.operator("kinetica.apply_preset", text="Swing",  icon='IPO_EASE_IN_OUT')
        op.preset = 'SWING'
        layout.prop(props, "shake_strength")


class KINETICA_PT_Cleanup(Panel):
    bl_parent_id   = "KINETICA_PT_main"
    bl_label       = "Cleanup"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Kinetica"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.scale_y = 1.3
        row = col.row(align=True)
        row.alert = True
        row.operator("kinetica.remove_fade",
                     text="Remove Fade", icon='X')
        col.operator("kinetica.refresh_drivers",
                     text="Refresh Drivers", icon='FILE_REFRESH')
        layout.separator(factor=0.3)
        col = layout.column(align=True)
        col.scale_y = 1.3
        col.operator("kinetica.clear_transforms",
                     text="Clear Transform Animation", icon='KEYFRAME')
        row = col.row(align=True)
        row.alert = True
        row.operator("kinetica.clear_all",
                     text="Clear EVERYTHING", icon='TRASH')


class KINETICA_PT_Info(Panel):
    bl_parent_id   = "KINETICA_PT_main"
    bl_label       = "Selection Info"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "Kinetica"

    def draw(self, context):
        layout = self.layout
        obj    = context.active_object
        if obj and obj.type in VALID:
            col = layout.column(align=True)
            col.label(text=f"Active:  {obj.name}", icon='OBJECT_DATA')
            col.label(text=f"Materials:  {len([s for s in obj.material_slots if s.material])}",
                      icon='MATERIAL')
            if PROP in obj:
                av = _eval_alpha(obj, context)
                col.label(text=f"Opacity:  {int(av*100)}%  ({av:.3f})",
                          icon='DRIVER')
                layout.prop(obj, f'["{PROP}"]', text="Opacity", slider=True)
        else:
            layout.label(text="No valid object selected.", icon='ERROR')
        sel = [o for o in context.selected_objects if o.type in VALID]
        if len(sel) > 1:
            faded = sum(1 for o in sel if PROP in o)
            layout.label(text=f"Selected: {len(sel)}  |  With Fade: {faded}",
                         icon='GROUP')


# ═════════ Register ═════════
classes = (
    AutoFadeProperties,
    KINETICA_OT_FadeIn,
    KINETICA_OT_FadeOut,
    KINETICA_OT_RemoveFade,
    KINETICA_OT_RefreshDrivers,
    KINETICA_OT_ApplyPreset,
    KINETICA_OT_ClearTransforms,
    KINETICA_OT_ClearAll,
    KINETICA_PT_Main,
    KINETICA_PT_Fade,
    KINETICA_PT_Scale,
    KINETICA_PT_Move,
    KINETICA_PT_Rotate,
    KINETICA_PT_Loops,
    KINETICA_PT_Cleanup,
    KINETICA_PT_Info,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.kinetica_props = PointerProperty(type=AutoFadeProperties)


def unregister():
    if hasattr(bpy.types.Scene, 'kinetica_props'):
        del bpy.types.Scene.kinetica_props
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
