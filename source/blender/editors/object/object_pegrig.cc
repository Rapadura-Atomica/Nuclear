/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edobj
 *
 * Operators for the Nuclear peg rig: build a rig by binding Grease Pencil drawing objects to pegs.
 * Posing the pegs themselves is handled by the regular transform tools (see
 * `transform_convert_pegrig.cc`), which redirect a bound object's transform to its peg.
 */

#include "DNA_constraint_types.h"
#include "DNA_defs.h"
#include "DNA_layer_types.h"
#include "DNA_object_types.h"
#include "DNA_pegrig_types.h"
#include "DNA_scene_types.h"
#include "DNA_view3d_types.h"

#include "BLI_math_matrix.hh"
#include "BLI_math_vector.hh"
#include "BLI_string.h"
#include "BLI_vector.hh"

#include "BKE_constraint.h"
#include "BKE_context.hh"
#include "BKE_layer.hh"
#include "BKE_lib_id.hh"
#include "BKE_main.hh"
#include "BKE_object.hh"
#include "BKE_pegrig.hh"
#include "BKE_report.hh"

#include <optional>

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_build.hh"

#include "ED_object.hh"
#include "ED_screen.hh"
#include "ED_select_utils.hh"
#include "ED_view3d.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "object_intern.hh"

namespace blender::ed::object {

/* Collect the selected Grease Pencil objects. */
static Vector<Object *> selected_grease_pencil(bContext *C)
{
  Vector<Object *> targets;
  CTX_DATA_BEGIN (C, Object *, ob, selected_objects) {
    if (ob->type == OB_GREASE_PENCIL) {
      targets.append(ob);
    }
  }
  CTX_DATA_END;
  return targets;
}

/* Make `ob` a member of `rig` (a Follow Peg constraint targeting the rig). When `peg_index` is -1
 * the object belongs to the rig's composite but follows no peg: `followpeg_evaluate` no-ops on an
 * unresolved peg, so the drawing keeps its own transform until a peg is assigned later. */
static void object_bind_to_rig(Object *ob, PegRig *rig, int peg_index)
{
  bConstraint *con = BKE_object_find_followpeg_constraint(ob);
  if (con == nullptr) {
    con = BKE_constraint_add_for_object(ob, "Follow Peg", CONSTRAINT_TYPE_FOLLOWPEG);
  }
  bFollowPegConstraint *data = static_cast<bFollowPegConstraint *>(con->data);
  if (data->rig != rig) {
    if (data->rig != nullptr) {
      id_us_min(&data->rig->id);
    }
    data->rig = rig;
    id_us_plus(&rig->id);
  }
  if (peg_index >= 0 && peg_index < rig->pegs_num) {
    STRNCPY(data->peg_name, rig->pegs[peg_index].name);
    data->peg_index = peg_index;
    data->flag |= FOLLOWPEG_SET_INVERSE;
  }
  else {
    /* Loose member: belongs to the rig, follows no peg. */
    data->peg_name[0] = '\0';
    data->peg_index = -1;
  }
  DEG_id_tag_update(&ob->id, ID_RECALC_TRANSFORM);
}

static wmOperatorStatus pegrig_new_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);

  Vector<Object *> targets = selected_grease_pencil(C);
  if (targets.is_empty()) {
    BKE_report(op->reports, RPT_ERROR, "Select one or more Grease Pencil objects");
    return OPERATOR_CANCELLED;
  }

  char name[64];
  RNA_string_get(op->ptr, "name", name);
  PegRig *rig = BKE_pegrig_add(bmain, name[0] ? name : "PegRig");
  id_us_min(&rig->id);

  /* The rig is the composite: bind the selected drawings as members, without any peg yet. */
  for (Object *ob : targets) {
    object_bind_to_rig(ob, rig, -1);
  }
  rig->active_peg_index = -1;

  DEG_id_tag_update(&rig->id, ID_RECALC_PARAMETERS);
  DEG_relations_tag_update(bmain);
  WM_event_add_notifier(C, NC_OBJECT | ND_CONSTRAINT, nullptr);
  WM_event_add_notifier(C, NC_ID | NA_ADDED, nullptr);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_pegrig_new(wmOperatorType *ot)
{
  ot->name = "New Rig";
  ot->description = "Create a peg rig (composite) from the selected Grease Pencil drawings";
  ot->idname = "OBJECT_OT_pegrig_new";

  ot->exec = pegrig_new_exec;
  ot->poll = ED_operator_objectmode;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_string(ot->srna, "name", "PegRig", MAX_NAME, "Name", "Name for the new rig");
}

static wmOperatorStatus pegrig_peg_new_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);

  Vector<Object *> targets = selected_grease_pencil(C);

  /* A peg is added to the rig the selected drawings already belong to. The rig must exist first
   * (created with "New Rig"); the peg is born loose and receives drawings later (Peg Graph). */
  PegRig *rig = nullptr;
  for (Object *ob : targets) {
    if (bConstraint *con = BKE_object_find_followpeg_constraint(ob)) {
      bFollowPegConstraint *data = static_cast<bFollowPegConstraint *>(con->data);
      if (data->rig != nullptr) {
        rig = data->rig;
        break;
      }
    }
  }
  if (rig == nullptr) {
    BKE_report(op->reports,
               RPT_ERROR,
               "No peg rig for the selection: use \"New Rig\" first to create one");
    return OPERATOR_CANCELLED;
  }

  /* If the active object already follows a peg in this rig, nest the new peg under it. */
  int parent_index = -1;
  if (Object *active = CTX_data_active_object(C)) {
    if (bConstraint *con = BKE_object_find_followpeg_constraint(active)) {
      bFollowPegConstraint *data = static_cast<bFollowPegConstraint *>(con->data);
      if (data->rig == rig) {
        parent_index = BKE_pegrig_peg_index_by_name(rig, data->peg_name);
      }
    }
  }

  char name[64];
  RNA_string_get(op->ptr, "name", name);
  const int peg_index = BKE_pegrig_peg_add(rig, name[0] ? name : "Peg", parent_index);
  rig->active_peg_index = peg_index;

  DEG_id_tag_update(&rig->id, ID_RECALC_PARAMETERS);
  DEG_relations_tag_update(bmain);
  WM_event_add_notifier(C, NC_OBJECT | ND_CONSTRAINT, nullptr);
  WM_event_add_notifier(C, NC_ID | NA_ADDED, nullptr);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_pegrig_peg_new(wmOperatorType *ot)
{
  ot->name = "New Peg";
  ot->description = "Add a peg to the rig of the selected drawings (the peg starts unbound)";
  ot->idname = "OBJECT_OT_pegrig_peg_new";

  ot->exec = pegrig_peg_new_exec;
  ot->poll = ED_operator_objectmode;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_string(ot->srna, "name", "Peg", MAX_NAME, "Name", "Name for the new peg");
}

/* -------------------------------------------------------------------- */
/** \name Peg Pose pick + hierarchy navigation
 * \{ */

static bFollowPegConstraint *active_followpeg(Object *ob)
{
  bConstraint *con = BKE_object_find_followpeg_constraint(ob);
  return con ? static_cast<bFollowPegConstraint *>(con->data) : nullptr;
}

static wmOperatorStatus pegrig_pick_invoke(bContext *C, wmOperator * /*op*/, const wmEvent *event)
{
  Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  View3D *v3d = CTX_wm_view3d(C);

  Base *base = ED_view3d_give_base_under_cursor(C, event->mval);

  base_deselect_all(scene, view_layer, v3d, SEL_DESELECT);

  if (base != nullptr && BASE_SELECTABLE(v3d, base)) {
    base_select(base, BA_SELECT);
    base_activate(C, base);

    /* Re-anchor the rig's active peg to the clicked drawing's own peg (the leaf), so a fresh click
     * resets the Ctrl+B hierarchy navigation back to the bottom. */
    if (bFollowPegConstraint *data = active_followpeg(base->object)) {
      if (data->rig != nullptr) {
        data->rig->active_peg_index = BKE_pegrig_peg_index_by_name(data->rig, data->peg_name);
      }
    }
  }

  WM_event_add_notifier(C, NC_SCENE | ND_OB_SELECT, scene);
  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, nullptr);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_pegrig_pick(wmOperatorType *ot)
{
  ot->name = "Pick Peg";
  ot->description = "Select the drawing under the cursor and make its peg the active one";
  ot->idname = "OBJECT_OT_pegrig_pick";

  ot->invoke = pegrig_pick_invoke;
  ot->poll = ED_operator_view3d_active;

  ot->flag = OPTYPE_UNDO;
}

static bool pegrig_select_parent_poll(bContext *C)
{
  Object *ob = CTX_data_active_object(C);
  return ob != nullptr && BKE_object_find_followpeg_constraint(ob) != nullptr;
}

static wmOperatorStatus pegrig_select_parent_exec(bContext *C, wmOperator * /*op*/)
{
  Object *ob = CTX_data_active_object(C);
  bFollowPegConstraint *data = ob ? active_followpeg(ob) : nullptr;
  if (data == nullptr || data->rig == nullptr) {
    return OPERATOR_CANCELLED;
  }
  PegRig *rig = data->rig;

  const int obj_peg = BKE_pegrig_peg_index_by_name(rig, data->peg_name);
  if (obj_peg < 0) {
    return OPERATOR_CANCELLED;
  }

  /* The peg currently being controlled: the active peg if it is the object's own peg or an
   * ancestor of it (mid-climb), otherwise the object's own peg. */
  int current = obj_peg;
  const int active = rig->active_peg_index;
  if (active >= 0 && active < rig->pegs_num &&
      (active == obj_peg || BKE_pegrig_peg_is_ancestor(rig, active, obj_peg)))
  {
    current = active;
  }

  const int parent = rig->pegs[current].parent_index;
  if (parent < 0) {
    return OPERATOR_CANCELLED;
  }
  rig->active_peg_index = parent;

  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, nullptr);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_pegrig_select_parent(wmOperatorType *ot)
{
  ot->name = "Select Parent Peg";
  ot->description = "Make the parent of the active peg the controlled peg (climb the rig hierarchy)";
  ot->idname = "OBJECT_OT_pegrig_select_parent";

  ot->exec = pegrig_select_parent_exec;
  ot->poll = pegrig_select_parent_poll;

  ot->flag = OPTYPE_UNDO;
}

/** \} */

/* -------------------------------------------------------------------- */
/** \name Squash & Stretch (see SquashFeature.md)
 * \{ */

/* Resolve the peg the active object's rig is currently controlling: the rig's active peg, falling
 * back to the active object's own peg. Returns false when there is no such peg. */
static bool squash_active_peg(bContext *C, PegRig **r_rig, int *r_index)
{
  Object *ob = CTX_data_active_object(C);
  bFollowPegConstraint *data = ob ? active_followpeg(ob) : nullptr;
  if (data == nullptr || data->rig == nullptr) {
    return false;
  }
  PegRig *rig = data->rig;
  int index = rig->active_peg_index;
  if (index < 0 || index >= rig->pegs_num) {
    index = BKE_pegrig_peg_index_by_name(rig, data->peg_name);
  }
  if (index < 0 || index >= rig->pegs_num) {
    return false;
  }
  *r_rig = rig;
  *r_index = index;
  return true;
}

static bool pegrig_squash_poll(bContext *C)
{
  PegRig *rig;
  int index;
  return squash_active_peg(C, &rig, &index);
}

static wmOperatorStatus pegrig_squash_enable_exec(bContext *C, wmOperator *op)
{
  PegRig *rig;
  int peg_index;
  if (!squash_active_peg(C, &rig, &peg_index)) {
    BKE_report(op->reports, RPT_ERROR, "No active peg to enable squash on");
    return OPERATOR_CANCELLED;
  }
  PegRigPeg *peg = &rig->pegs[peg_index];

  /* Fit the anchor (bottom) and tip (top) to the world-space bounds of every Grease Pencil object
   * following this peg, so a fresh enable gives a vertical squash axis spanning the body. */
  Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  bool has_bounds = false;
  float3 wmin(0.0f);
  float3 wmax(0.0f);
  FOREACH_OBJECT_BEGIN (scene, view_layer, ob) {
    if (ob->type != OB_GREASE_PENCIL) {
      continue;
    }
    bFollowPegConstraint *data = active_followpeg(ob);
    if (data == nullptr || data->rig != rig || !STREQ(data->peg_name, peg->name)) {
      continue;
    }
    const std::optional<Bounds<float3>> bounds = BKE_object_boundbox_get(ob);
    if (!bounds) {
      continue;
    }
    const float4x4 &obmat = ob->object_to_world();
    for (int corner = 0; corner < 8; corner++) {
      const float3 local((corner & 1) ? bounds->max.x : bounds->min.x,
                         (corner & 2) ? bounds->max.y : bounds->min.y,
                         (corner & 4) ? bounds->max.z : bounds->min.z);
      const float3 world = math::transform_point(obmat, local);
      wmin = has_bounds ? math::min(wmin, world) : world;
      wmax = has_bounds ? math::max(wmax, world) : world;
      has_bounds = true;
    }
  }
  FOREACH_OBJECT_END;

  float3 anchor(0.0f, 0.0f, 0.0f);
  float3 tip(0.0f, 0.0f, 1.0f);
  if (has_bounds) {
    /* Vertical axis is Z (the cut-out drawing plane is XZ; Y is depth). Span the body bottom->top
     * along Z, centred in X and Y. */
    const float cx = 0.5f * (wmin.x + wmax.x);
    const float cy = 0.5f * (wmin.y + wmax.y);
    /* Anchor/tip live in the peg's OWN local space (so the squash follows the rig when posed); map
     * the world bottom/top centres into it. The squash flag is still off here, so the solved world
     * matrix carries no squash. */
    BKE_pegrig_solve_world_matrices(rig);
    float peg_world[4][4];
    BKE_pegrig_peg_world_matrix_get(rig, peg_index, peg_world);
    const float4x4 to_local = math::invert(float4x4(peg_world));
    anchor = math::transform_point(to_local, float3(cx, cy, wmin.z));
    tip = math::transform_point(to_local, float3(cx, cy, wmax.z));
    if (math::distance(anchor, tip) < 1e-5f) {
      tip = anchor + float3(0.0f, 0.0f, 1.0f);
    }
  }

  peg->squash_anchor[0] = anchor.x;
  peg->squash_anchor[1] = anchor.y;
  peg->squash_anchor[2] = anchor.z;
  peg->squash_tip[0] = tip.x;
  peg->squash_tip[1] = tip.y;
  peg->squash_tip[2] = tip.z;
  /* The deform driver (BKE_pegrig: `s = (squash_tip.z - anchor.z) / squash_rest_len`) measures the
   * vertical (local-Z) span only, so the rest length MUST be that same Z delta - not the full 3D
   * distance. Using `distance()` made `s < 1` at rest for any in-plane-rotated (posed) peg, popping
   * the drawing the instant squash was enabled. The driver's `> 1e-6f` guard skips a degenerate
   * (near-horizontal / inverted) span. */
  peg->squash_rest_len = tip.z - anchor.z;
  if (peg->squash_volume <= 0.0f) {
    peg->squash_volume = 1.0f;
  }
  peg->flag |= PEGRIGPEG_SQUASH;

  DEG_id_tag_update(&rig->id, ID_RECALC_PARAMETERS);
  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, nullptr);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_pegrig_squash_enable(wmOperatorType *ot)
{
  ot->name = "Enable Squash";
  ot->description =
      "Enable squash & stretch on the active peg, fitting the anchor and tip to its drawings";
  ot->idname = "OBJECT_OT_pegrig_squash_enable";

  ot->exec = pegrig_squash_enable_exec;
  ot->poll = pegrig_squash_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

static wmOperatorStatus pegrig_squash_reset_rest_exec(bContext *C, wmOperator * /*op*/)
{
  PegRig *rig;
  int peg_index;
  if (!squash_active_peg(C, &rig, &peg_index)) {
    return OPERATOR_CANCELLED;
  }
  PegRigPeg *peg = &rig->pegs[peg_index];
  /* Match the Z-only deform driver (see pegrig_squash_enable_exec): rest length is the vertical
   * span, not the 3D distance, so the current pose reads back as s == 1 (identity) at rest. */
  const float len = peg->squash_tip[2] - peg->squash_anchor[2];
  peg->squash_rest_len = (len > 1e-6f) ? len : 1.0f;

  DEG_id_tag_update(&rig->id, ID_RECALC_PARAMETERS);
  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, nullptr);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_pegrig_squash_reset_rest(wmOperatorType *ot)
{
  ot->name = "Reset Squash Rest";
  ot->description = "Recapture the rest length from the current anchor-to-tip distance";
  ot->idname = "OBJECT_OT_pegrig_squash_reset_rest";

  ot->exec = pegrig_squash_reset_rest_exec;
  ot->poll = pegrig_squash_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

/** \} */

}  // namespace blender::ed::object
