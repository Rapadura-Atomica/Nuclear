"""Self-test for the bind controls of the `Rig > Deform Curve` panel.

    nuclear -b <rig.blend> -P tools/nuclear_rig/selftest_deform_curve_panel.py

Binding is the switch that decides whether a deform curve moves the drawing at all: an unbound
Curve modifier sits on the stack and does nothing, silently. So what the panel SAYS about that
state is not decoration, and it is what this file checks.

The panel's `draw()` is run for real, against a stand-in layout that records every label,
operator, `enabled` flag and assigned property. That covers the whole decision -- scope phrase,
Bind vs Bind Again, the greyed-out Unbind -- without a window, since this machine has no Xvfb and
`draw()` never runs in background mode.

The checks adapt to the rig they are given (one curve or eight, all bound or half), because the
interesting states are exactly the ones a real file arrives in. Run it on a few: a fully bound
rig never exercises the "not bound" wording, and a rig with one curve never exercises the plural.
"""
import sys

import bpy

import nuclear_deform_curve as ndc

fails = []
total = 0


def check(label, got, want):
    global total
    total += 1
    ok = got == want
    print("%-52s %s   got=%r" % (label, "OK " if ok else "FAIL", got))
    if not ok:
        fails.append("%s: got %r want %r" % (label, got, want))


class FakeOpProps:
    """What `layout.operator()` hands back: the property bag the panel fills in."""

    def __init__(self):
        self.assigned = {}

    def __setattr__(self, name, value):
        if name == "assigned":
            object.__setattr__(self, name, value)
        else:
            self.assigned[name] = value


class FakeLayout:
    """Stand-in for UILayout: records labels, operators and the inherited greyed-out state."""

    def __init__(self, log, enabled=True):
        object.__setattr__(self, "_log", log)
        object.__setattr__(self, "enabled", enabled)
        object.__setattr__(self, "scale_y", 1.0)

    def _child(self):
        # A sub-layout inherits `enabled`, the way a real one does.
        return FakeLayout(self._log, self.enabled)

    def row(self, **_kw):
        return self._child()

    def column(self, **_kw):
        return self._child()

    def box(self, **_kw):
        return self._child()

    def separator(self, **_kw):
        pass

    def label(self, text="", icon="NONE", **_kw):
        self._log.append(("label", "", text, self.enabled, icon))

    def operator(self, idname, text="", icon="NONE", **_kw):
        props = FakeOpProps()
        self._log.append(("op", idname, text, self.enabled, icon, props))
        return props


def draw_panel():
    log = []
    panel = bpy.types.VIEW3D_PT_nuclear_deform_curve

    class Shim:
        pass

    shim = Shim()
    shim.layout = FakeLayout(log)
    panel.draw(shim, bpy.context)
    return log


def show(log, title):
    print("\n%s" % title)
    for entry in log:
        kind, idname, text, enabled = entry[:4]
        extra = "  %r" % entry[5].assigned if kind == "op" else ""
        print("   %-6s %-32s %-14r%s%s" % (kind, idname, text, "" if enabled else "  [greyed]", extra))


def texts(log):
    return [e[2] for e in log]


def button(log, text):
    for entry in log:
        if entry[0] == "op" and entry[2] == text:
            return entry[1], entry[3], entry[5].assigned
    return None, None, {}


bpy.ops.object.select_all(action="DESELECT")
pieces = ndc._curve_pieces(bpy.context, selected_only=False)
if not pieces:
    print("This file has no piece with a deform curve -- nothing to test")
    sys.exit(0)
print("pieces carrying a deform curve: %d" % len(pieces))

# --- 1. no selection: the whole file is the target, and the panel has to say so ---
bound_now = sum(1 for ob, _md in pieces if ndc._has_binding(ob))
log = draw_panel()
show(log, "PANEL (nothing selected, %d of %d bound):" % (bound_now, len(pieces)))
expected = ("Acts on the only visible piece" if len(pieces) == 1
            else "Acts on all %d visible pieces" % len(pieces))
check("scope names the whole file", expected in texts(log), True)

# The wording has to follow the state of the file: full, empty or half way.
if bound_now == len(pieces):
    check("all bound -> Bind Again, no count",
          (button(log, "Bind Again")[0], [t for t in texts(log) if t.endswith(" bound")]),
          ("object.nuclear_curve_bind", []))
    idname, _enabled, props = button(log, "Bind Again")
elif bound_now == 0:
    check("none bound -> the no-op is spelled out",
          "not bound — the curve deforms nothing" in texts(log), True)
    idname, _enabled, props = button(log, "Bind")
else:
    check("half way -> the count is admitted",
          "%d of %d bound" % (bound_now, len(pieces)) in texts(log), True)
    idname, _enabled, props = button(log, "Bind")
check("a bind button is there", idname, "object.nuclear_curve_bind")
check("and it binds rather than unbinds", props.get("unbind"), False)

idname, enabled, _props = button(log, "Unbind")
check("Unbind is there and clickable", (idname, enabled), ("object.nuclear_curve_unbind", True))
check("and it is an operator of its own, so F9 and search name it right",
      bpy.types.OBJECT_OT_nuclear_curve_unbind.bl_label, "Unbind from Curve")
check("Restamp keeps its own row and full label",
      [e[2] for e in log if e[1] == "object.nuclear_curve_refresh"], [""])

# --- 2. one piece selected: the scope narrows with the selection ---
first = pieces[0][0]
first.select_set(True)
bpy.context.view_layer.objects.active = first
log = draw_panel()
check("scope narrows to the selection", "Acts on the selected piece" in texts(log), True)
check("an already bound piece offers Bind Again", button(log, "Bind Again")[0],
      "object.nuclear_curve_bind")
check("and no count is repeated when everything is bound",
      [t for t in texts(log) if t.endswith(" bound")], [])

# --- 3. an unbound piece: greyed-out Unbind, and the no-op said out loud ---
bpy.ops.object.nuclear_curve_unbind()
check("the old spelling still works, for scripts written against it",
      bpy.ops.object.nuclear_curve_bind(unbind=True), {"FINISHED"})
log = draw_panel()
show(log, "PANEL (the selected piece unbound):")
check("warns that the curve deforms nothing",
      "not bound — the curve deforms nothing" in texts(log), True)
check("the button goes back to Bind", button(log, "Bind")[0], "object.nuclear_curve_bind")
check("Unbind is greyed out", button(log, "Unbind")[1], False)

# --- 4. a partly bound selection must not promise Bind Again ---
if len(pieces) > 1:
    pieces[1][0].select_set(True)
    log = draw_panel()
    check("counts what is bound", "1 of 2 bound" in texts(log), True)
    check("no Bind Again over a partial selection", button(log, "Bind Again")[0], None)
    bpy.ops.object.nuclear_curve_bind()
    check("bind lands on both", sum(1 for ob, _md in pieces[:2] if ndc._has_binding(ob)), 2)
else:
    bpy.ops.object.nuclear_curve_bind()
    log = draw_panel()
    check("a one-curve rig names its single piece",
          "Acts on the selected piece" in texts(log), True)
    check("and offers Bind Again again", button(log, "Bind Again")[0],
          "object.nuclear_curve_bind")

print("\n%s  (%d/%d)" % ("ALL PASSED" if not fails else "FAILURES: " + " | ".join(fails),
                         total - len(fails), total))
sys.exit(1 if fails else 0)
