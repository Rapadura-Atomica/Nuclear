# SPDX-FileCopyrightText: 2026 Blender Authors
#
# SPDX-License-Identifier: GPL-2.0-or-later
"""Nuclear — reuse a peg animation on another character.

A PegRig action is portable *by construction*. Every peg's rest matrix is the identity:
``T(t+p) · R · S · T(-p)`` with ``t=0, R=I, S=1`` collapses to ``T(p) · T(-p) = I``,
whatever the pivot is. There is no rest pose to conjugate through, so copying a rotation
curve from one character to another is exact rather than approximate — the opposite of
armature retargeting, where ``B_src != B_tgt`` is the source of every artefact.

The Auto Rig names joint pegs after the ROLE (``_ROLE_LABEL``: Tronco, Braço.e, Coxa.d…)
precisely because piece names in a legacy library lie. That turns the name match here into a
contract instead of a heuristic: two characters built by Auto-Build Skeleton (or by Convert
Armature to Pegs) share peg names because they were named by the same table.

So this module stays deliberately small: match pegs by name, copy the channels that are safe
to copy, and refuse to touch anything that describes the destination's *anatomy* rather than
the *performance*.

**Do no harm** is the rule throughout — never create or reparent a peg, never overwrite a
pivot, never delete the destination's previous action, never guess a proportion. Anything
that cannot cross faithfully is skipped and reported. A dropped channel costs the animator
one fix they can see; a silently mistransferred one costs a hunt.

Pure Python over the existing PegRig API; no C side.
"""

import unicodedata

import bpy
from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    PointerProperty,
    StringProperty,
)
from bpy.types import Operator, Panel, PropertyGroup

# Drawing pegs carry the piece's own art fit-up, joints carry the performance. Kept in sync with
# nuclear_rig_auto._DRAW_PEG_SUFFIX, which is imported when available.
_DRAW_PEG_SUFFIX = " (ctrl)"


def _draw_peg_suffix():
    """The studio's drawing-peg suffix, from the Auto Rig when it is loaded."""
    try:
        import nuclear_rig_auto

        return nuclear_rig_auto._DRAW_PEG_SUFFIX
    except Exception:
        return _DRAW_PEG_SUFFIX


# --------------------------------------------------------------------------- #
# Transfer policy
# --------------------------------------------------------------------------- #
# Which peg properties may cross between characters, and on what grounds.
#
# EXACT        dimensionless — the same number means the same thing on any body. The bulk of a
#              cut-out performance lives here.
# PROPORTIONAL world units — faithful only while both characters are the same size.
# RIG_OWNED    describes where the destination's joints ARE, not what they do. Copying these
#              would rebuild the target's anatomy out of the source's body.
# REMAPPED     meaningful only relative to a RIG_OWNED value; carried across as intent.
_EXACT = frozenset({"rotation", "scale", "opacity", "use_squash", "squash_volume"})
_PROPORTIONAL = frozenset({"translation"})
_RIG_OWNED = frozenset({"pivot", "squash_anchor", "squash_rest_len"})
_REMAPPED = frozenset({"squash_tip"})

_KNOWN = _EXACT | _PROPORTIONAL | _RIG_OWNED | _REMAPPED

# Reasons a channel was not transferred, in the order they are reported.
_SKIP_NO_PEG = "peg missing in target"
_SKIP_RIG_OWNED = "belongs to the target's rig"
_SKIP_ART_FIT = "drawing-peg fit-up"
_SKIP_NO_SQUASH = "squash not set up on the target peg"
_SKIP_UNKNOWN = "unknown property"


# --------------------------------------------------------------------------- #
# Data paths
# --------------------------------------------------------------------------- #
def _unescape(text):
    return text.replace('\\"', '"').replace("\\\\", "\\")


def _escape(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _split_path(data_path):
    """``pegs["Braço.e"].rotation`` -> ``("Braço.e", "rotation")``, or ``(None, None)``."""
    if not data_path.startswith('pegs["'):
        return None, None
    end = data_path.rfind('"].')
    if end < 0:
        return None, None
    return _unescape(data_path[6:end]), data_path[end + 3:]


def _make_path(peg_name, prop):
    return 'pegs["%s"].%s' % (_escape(peg_name), prop)


def _iter_fcurves(action):
    """Every f-curve of a (slotted) action, whatever slot or layer it sits in."""
    for layer in action.layers:
        for strip in layer.strips:
            for cbag in strip.channelbags:
                for fcurve in cbag.fcurves:
                    yield fcurve


# --------------------------------------------------------------------------- #
# Name matching
# --------------------------------------------------------------------------- #
def _normalise(name):
    """Fold case and accents so a legacy 'BRACO.E' still meets 'Braço.e'.

    Only ever used as a *fallback* after an exact match fails: the role vocabulary is
    accented (Pescoço, Braço, Mão, Pé) and hand-built or imported rigs do not always keep the
    diacritics.
    """
    decomposed = unicodedata.normalize("NFD", name)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def _strip_number_suffix(name):
    """'Cabeça.001' -> 'Cabeça'. Only the Blender-style numeric suffix, never '.e'/'.d'."""
    base, dot, tail = name.rpartition(".")
    if dot and tail.isdigit() and len(tail) == 3:
        return base
    return name


def match_pegs(src_rig, tgt_rig, animated_names, ignore_number_suffix=False):
    """Pair source peg names with target pegs.

    Returns ``(pairs, missing)`` where ``pairs`` is a list of ``(src_name, tgt_name)`` and
    ``missing`` lists the animated source pegs with no counterpart. Exact names win over
    every fallback, and a target peg is claimed at most once — an ambiguous fallback is
    dropped rather than allowed to overwrite a channel that already matched.
    """
    target_names = [peg.name for peg in tgt_rig.pegs]
    exact = set(target_names)

    by_normalised = {}
    by_base = {}
    for name in target_names:
        by_normalised.setdefault(_normalise(name), name)
        if ignore_number_suffix:
            by_base.setdefault(_normalise(_strip_number_suffix(name)), name)

    pairs = []
    missing = []
    claimed = set()

    candidates = sorted(animated_names)

    # Pass 1: identical names. These are never displaced by a fallback below.
    for name in candidates:
        if name in exact:
            pairs.append((name, name))
            claimed.add(name)

    # Pass 2: accent/case fold, then the optional .001 fold.
    for name in candidates:
        if name in exact:
            continue
        found = by_normalised.get(_normalise(name))
        if found is None and ignore_number_suffix:
            found = by_base.get(_normalise(_strip_number_suffix(name)))
        if found is None or found in claimed:
            missing.append(name)
            continue
        pairs.append((name, found))
        claimed.add(found)

    return pairs, missing


def hierarchy_mismatches(src_rig, tgt_rig, pairs):
    """Matched pegs whose parent differs between the rigs.

    The transfer is per-peg, so a peg that hangs somewhere else in the target accumulates a
    different parent chain and will not land on the same pose. Reported, never blocking:
    the animator is the one who knows whether that limb matters in this shot.
    """
    src_by_name = {peg.name: index for index, peg in enumerate(src_rig.pegs)}
    tgt_by_name = {peg.name: index for index, peg in enumerate(tgt_rig.pegs)}

    def parent_name(rig, index):
        parent_index = rig.pegs[index].parent_index
        if parent_index < 0 or parent_index >= len(rig.pegs):
            return None
        return rig.pegs[parent_index].name

    out = []
    matched = dict(pairs)
    for src_name, tgt_name in pairs:
        src_parent = parent_name(src_rig, src_by_name[src_name])
        tgt_parent = parent_name(tgt_rig, tgt_by_name[tgt_name])
        # The source parent's own match is what the target parent ought to be.
        expected = matched.get(src_parent, src_parent)
        if expected != tgt_parent:
            out.append((src_name, src_parent, tgt_parent))
    return out


# --------------------------------------------------------------------------- #
# Proportion
# --------------------------------------------------------------------------- #
def _pivot_distance(rig, index):
    """Distance from a peg's pivot to its parent's — the peg's 'bone length'.

    At rest every local matrix is the identity, so a peg's ``pivot`` reads directly in rig
    coordinates and this distance is the real limb segment. Returns None at the root.
    """
    peg = rig.pegs[index]
    parent_index = peg.parent_index
    if parent_index < 0 or parent_index >= len(rig.pegs):
        return None
    delta = [a - b for a, b in zip(peg.pivot, rig.pegs[parent_index].pivot)]
    return sum(component * component for component in delta) ** 0.5


def limb_ratio(src_rig, tgt_rig, pairs):
    """Median target/source limb ratio over matched pegs, or None if nothing is measurable.

    Median, not mean: a root or prop peg with an arbitrary pivot would drag an average
    anywhere, and one bad segment must not rescale a whole performance.
    """
    src_by_name = {peg.name: index for index, peg in enumerate(src_rig.pegs)}
    tgt_by_name = {peg.name: index for index, peg in enumerate(tgt_rig.pegs)}

    ratios = []
    for src_name, tgt_name in pairs:
        src_length = _pivot_distance(src_rig, src_by_name[src_name])
        tgt_length = _pivot_distance(tgt_rig, tgt_by_name[tgt_name])
        if src_length and tgt_length and src_length > 1e-6:
            ratios.append(tgt_length / src_length)

    if not ratios:
        return None
    ratios.sort()
    middle = len(ratios) // 2
    if len(ratios) % 2:
        return ratios[middle]
    return (ratios[middle - 1] + ratios[middle]) / 2.0


# --------------------------------------------------------------------------- #
# Curve writing
# --------------------------------------------------------------------------- #
def _affine_y(fcurve, factor, offset):
    """``y -> factor*y + offset`` on keys and handles.

    Affine on the value axis only, so timing, interpolation mode and handle *shape* survive
    untouched — the curve keeps the animator's easing, just at a different amplitude.
    """
    if factor == 1.0 and offset == 0.0:
        return
    for keyframe in fcurve.keyframe_points:
        keyframe.co.y = factor * keyframe.co.y + offset
        keyframe.handle_left.y = factor * keyframe.handle_left.y + offset
        keyframe.handle_right.y = factor * keyframe.handle_right.y + offset
    fcurve.update()


def _destination_channelbag(action, slot):
    layer = action.layers[0] if len(action.layers) else action.layers.new("Layer")
    strip = layer.strips[0] if len(layer.strips) else layer.strips.new(type="KEYFRAME")
    return strip.channelbag(slot, ensure=True)


def _squash_remap(src_rig, tgt_rig, src_name, tgt_name, array_index):
    """Affine terms that carry a squash_tip curve across as *intent*.

    The squash factor is ``s = (tip.z - anchor.z) / rest_len``, and both ``anchor`` and
    ``rest_len`` belong to the rig. Copying tip.z raw would hand a tall character's numbers to
    a short one. Reproducing ``s`` instead gives ``tip.z' = anchor'.z + s·rest'``, i.e. an
    affine map on the value. Only the vertical component (index 2) drives the squash; the
    others are art fit-up and are left alone.

    Returns ``(factor, offset)``, or None when the target peg has no squash set up — in which
    case the channel is skipped rather than written as noise.
    """
    if array_index != 2:
        return None
    src_peg = src_rig.pegs[src_name]
    tgt_peg = tgt_rig.pegs[tgt_name]
    src_rest = src_peg.squash_rest_len
    tgt_rest = tgt_peg.squash_rest_len
    if src_rest <= 1e-6 or tgt_rest <= 1e-6 or not tgt_peg.use_squash:
        return None
    factor = tgt_rest / src_rest
    return factor, tgt_peg.squash_anchor[2] - factor * src_peg.squash_anchor[2]


def plan_transfer(src_rig, tgt_rig, action, settings):
    """Decide, channel by channel, what crosses and what does not.

    Returns ``(moves, skips)``. A move is ``(fcurve, target_path, factor, offset)``; a skip is
    ``(data_path, reason)``. Nothing is written here — the same plan backs both the preview
    and the apply, so what the animator is shown is exactly what will happen.
    """
    animated = set()
    for fcurve in _iter_fcurves(action):
        peg_name, prop = _split_path(fcurve.data_path)
        if peg_name is not None and prop in _KNOWN:
            animated.add(peg_name)

    pairs, missing = match_pegs(
        src_rig, tgt_rig, animated, settings.ignore_number_suffix
    )
    mapping = dict(pairs)

    if settings.scale_mode == "AUTO":
        measured = limb_ratio(src_rig, tgt_rig, pairs)
        proportion = measured if measured else 1.0
    elif settings.scale_mode == "MANUAL":
        proportion = settings.scale_factor
    else:
        proportion = 1.0

    suffix = _draw_peg_suffix()
    moves = []
    skips = []

    for fcurve in _iter_fcurves(action):
        path = fcurve.data_path
        peg_name, prop = _split_path(path)
        if peg_name is None:
            continue
        if prop not in _KNOWN:
            skips.append((path, _SKIP_UNKNOWN))
            continue
        if prop in _RIG_OWNED:
            skips.append((path, _SKIP_RIG_OWNED))
            continue

        tgt_name = mapping.get(peg_name)
        if tgt_name is None:
            skips.append((path, _SKIP_NO_PEG))
            continue

        factor, offset = 1.0, 0.0

        if prop in _PROPORTIONAL:
            if settings.translation_mode == "NONE":
                skips.append((path, "translation off"))
                continue
            if settings.translation_mode == "JOINTS" and peg_name.endswith(suffix):
                skips.append((path, _SKIP_ART_FIT))
                continue
            factor = proportion
        elif prop in _REMAPPED:
            if not settings.copy_squash:
                skips.append((path, "squash off"))
                continue
            remap = _squash_remap(
                src_rig, tgt_rig, peg_name, tgt_name, fcurve.array_index
            )
            if remap is None:
                skips.append((path, _SKIP_NO_SQUASH))
                continue
            factor, offset = remap
        elif prop.startswith("squash") and not settings.copy_squash:
            skips.append((path, "squash off"))
            continue

        moves.append((fcurve, _make_path(tgt_name, prop), factor, offset))

    return moves, skips, pairs, missing, proportion


def apply_transfer(tgt_rig, moves, action_name):
    """Write the planned curves into a fresh action on the target rig.

    The destination's previous action is given a fake user before being swapped out, so a
    reuse never costs the animator work that already existed.
    """
    new_action = bpy.data.actions.new(action_name)
    new_action.use_fake_user = True
    slot = new_action.slots.new("PEGRIG", tgt_rig.name)
    channelbag = _destination_channelbag(new_action, slot)

    written = 0
    for fcurve, path, factor, offset in moves:
        copied = channelbag.fcurves.new_from_fcurve(fcurve, data_path=path)
        if copied is None:
            continue
        _affine_y(copied, factor, offset)
        written += 1

    if tgt_rig.animation_data is None:
        tgt_rig.animation_data_create()
    previous = tgt_rig.animation_data.action
    if previous is not None and previous != new_action:
        previous.use_fake_user = True
    tgt_rig.animation_data.action = new_action
    tgt_rig.animation_data.action_slot = slot

    return new_action, written


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #
class NuclearPegReuseSettings(PropertyGroup):
    source_rig: PointerProperty(
        name="From", type=bpy.types.PegRig,
        description="The character whose animation you want to reuse")
    source_action: PointerProperty(
        name="Animation", type=bpy.types.Action,
        description="Which animation to reuse. Leave empty to use the one the source rig is "
                    "playing")
    target_rig: PointerProperty(
        name="To", type=bpy.types.PegRig,
        description="The character that receives the animation")
    new_action_name: StringProperty(
        name="New Name", default="",
        description="Leave empty to name it after both characters")

    ignore_number_suffix: BoolProperty(
        name="Match .001 names", default=False,
        description="Let 'Cabeça' match 'Cabeça.001'. Off by default: it can pair two pegs "
                    "that only look alike")
    translation_mode: EnumProperty(
        name="Translation", default="JOINTS",
        items=[
            ("JOINTS", "Joints only",
             "Move the joints, leave each drawing peg where the artist fitted it"),
            ("ALL", "Everything", "Also move the drawing pegs. Can unfit the artwork"),
            ("NONE", "None", "Rotation and scale only — the safest transfer"),
        ],
        description="Rotation always crosses exactly; translation is in world units, so it "
                    "only lands right when the two characters are built alike")
    scale_mode: EnumProperty(
        name="Proportion", default="NONE",
        items=[
            ("NONE", "Keep as is", "Copy the movement unchanged"),
            ("AUTO", "Measured", "Scale by the measured limb ratio between the two rigs"),
            ("MANUAL", "Set by hand", "Type the proportion yourself"),
        ],
        description="Only affects translation. Off by default — the measured ratio is shown "
                    "in the check so you can decide")
    scale_factor: FloatProperty(
        name="Factor", default=1.0, min=0.001, soft_max=10.0,
        description="2.0 = the new character is twice the size of the original")
    copy_squash: BoolProperty(
        name="Squash & stretch", default=True,
        description="Carry the squash across as intent, rescaled to the target's own span. "
                    "Pegs without squash set up are skipped")


# --------------------------------------------------------------------------- #
# Operators
# --------------------------------------------------------------------------- #
def _resolve_action(settings):
    if settings.source_action:
        return settings.source_action
    rig = settings.source_rig
    if rig and rig.animation_data and rig.animation_data.action:
        return rig.animation_data.action
    return None


def _validate(settings):
    """Shared guard. Returns an error string, or None when the settings are workable."""
    if not settings.source_rig or not settings.target_rig:
        return "Pick both characters."
    if settings.source_rig == settings.target_rig:
        return "Source and target are the same character."
    if _resolve_action(settings) is None:
        return "The source character has no animation."
    return None


class OBJECT_OT_nuclear_peg_reuse_check(Operator):
    """Report what would cross to the other character, without changing anything"""

    bl_idname = "object.nuclear_peg_reuse_check"
    bl_label = "Check"
    bl_options = {"REGISTER"}

    def execute(self, context):
        settings = context.scene.nuclear_peg_reuse
        error = _validate(settings)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        action = _resolve_action(settings)
        moves, skips, pairs, missing, proportion = plan_transfer(
            settings.source_rig, settings.target_rig, action, settings
        )
        mismatched = hierarchy_mismatches(
            settings.source_rig, settings.target_rig, pairs
        )
        measured = limb_ratio(settings.source_rig, settings.target_rig, pairs)

        print("\n[Peg Reuse] '%s': %s -> %s"
              % (action.name, settings.source_rig.name, settings.target_rig.name))
        print("  %d channel(s) cross, %d skipped, %d peg(s) matched"
              % (len(moves), len(skips), len(pairs)))
        for src_name, tgt_name in pairs:
            print("    %s  ->  %s" % (src_name, tgt_name))
        if missing:
            print("  NOT IN THE TARGET: %s" % ", ".join(sorted(missing)))
        for path, reason in skips:
            print("    skipped %s  (%s)" % (path, reason))
        for peg, src_parent, tgt_parent in mismatched:
            print("    DIFFERENT PARENT: '%s' hangs on '%s' here and on '%s' there"
                  % (peg, src_parent, tgt_parent))
        if measured:
            print("  measured limb ratio: %.4f" % measured)

        summary = "%d channels cross, %d skipped, %d pegs matched" % (
            len(moves), len(skips), len(pairs))
        if missing:
            summary += " | %d peg(s) missing" % len(missing)
        if mismatched:
            summary += " | %d hang elsewhere" % len(mismatched)
        if measured and abs(measured - 1.0) > 0.02:
            summary += " | limbs %.2fx" % measured
        self.report({"WARNING"} if (missing or mismatched) else {"INFO"}, summary)
        return {"FINISHED"}


class OBJECT_OT_nuclear_peg_reuse(Operator):
    """Copy the animation onto the other character as a new action"""

    bl_idname = "object.nuclear_peg_reuse"
    bl_label = "Reuse Animation"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        settings = context.scene.nuclear_peg_reuse
        error = _validate(settings)
        if error:
            self.report({"ERROR"}, error)
            return {"CANCELLED"}

        action = _resolve_action(settings)
        moves, skips, pairs, missing, proportion = plan_transfer(
            settings.source_rig, settings.target_rig, action, settings
        )
        if not moves:
            self.report({"ERROR"}, "Nothing could cross — check the peg names.")
            return {"CANCELLED"}

        name = settings.new_action_name.strip() or "%s_on_%s" % (
            action.name, settings.target_rig.name)
        new_action, written = apply_transfer(settings.target_rig, moves, name)

        summary = "'%s' — %d channels on %d pegs" % (
            new_action.name, written, len(pairs))
        if proportion != 1.0:
            summary += ", translation x%.3f" % proportion
        if skips:
            summary += " (%d skipped, see console)" % len(skips)
        if missing:
            summary += " (%d peg(s) missing)" % len(missing)
        for path, reason in skips:
            print("[Peg Reuse] skipped %s  (%s)" % (path, reason))
        self.report({"WARNING"} if (skips or missing) else {"INFO"}, summary)
        return {"FINISHED"}


# --------------------------------------------------------------------------- #
# Panel
# --------------------------------------------------------------------------- #
class VIEW3D_PT_nuclear_peg_reuse(Panel):
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Rig"
    bl_label = "Reuse Animation"
    bl_options = {"DEFAULT_CLOSED"}

    @classmethod
    def poll(cls, context):
        return len(bpy.data.pegrigs) > 1

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        settings = context.scene.nuclear_peg_reuse

        column = layout.column()
        column.prop(settings, "source_rig", icon="ARMATURE_DATA")
        column.prop(settings, "source_action", icon="ACTION")
        column.separator()
        column.prop(settings, "target_rig", icon="OUTLINER_OB_ARMATURE")

        layout.separator()
        column = layout.column()
        column.prop(settings, "translation_mode")
        column.prop(settings, "scale_mode")
        row = column.row()
        row.enabled = settings.scale_mode == "MANUAL"
        row.prop(settings, "scale_factor")
        column.prop(settings, "copy_squash")
        column.prop(settings, "ignore_number_suffix")

        layout.separator()
        column = layout.column()
        column.prop(settings, "new_action_name")

        layout.separator()
        actions = layout.column(align=True)
        actions.use_property_split = False
        ready = bool(settings.source_rig and settings.target_rig)
        if not ready:
            actions.label(text="Pick both characters", icon="INFO")
        elif settings.source_rig == settings.target_rig:
            actions.label(text="Both are the same character", icon="ERROR")
            ready = False

        check = actions.column(align=True)
        check.enabled = ready
        check.operator("object.nuclear_peg_reuse_check", icon="VIEWZOOM")

        run = actions.column(align=True)
        run.enabled = ready
        run.scale_y = 1.4
        run.operator("object.nuclear_peg_reuse", icon="PLAY")


# --------------------------------------------------------------------------- #
# Registration
# --------------------------------------------------------------------------- #
_classes = (
    NuclearPegReuseSettings,
    OBJECT_OT_nuclear_peg_reuse_check,
    OBJECT_OT_nuclear_peg_reuse,
    VIEW3D_PT_nuclear_peg_reuse,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.nuclear_peg_reuse = PointerProperty(type=NuclearPegReuseSettings)


def unregister():
    del bpy.types.Scene.nuclear_peg_reuse
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
