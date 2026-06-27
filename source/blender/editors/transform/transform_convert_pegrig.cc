/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 *
 * Object-mode transform of the peg that controls the active Grease Pencil object. When a drawing
 * object is bound to a peg (via a Follow Peg constraint), transforming it in object mode moves the
 * *peg* rather than the object itself (the Toon Boom cut-out posing workflow).
 */

#include "MEM_guardedalloc.h"

#include "DNA_constraint_types.h"
#include "DNA_object_types.h"
#include "DNA_pegrig_types.h"

#include "BLI_math_matrix.h"
#include "BLI_math_matrix.hh"
#include "BLI_math_vector.h"
#include "BLI_string.h"

#include "BKE_context.hh"
#include "BKE_layer.hh"
#include "BKE_pegrig.hh"
#include "BKE_scene.hh"

#include "ANIM_keyframing.hh"

#include "DEG_depsgraph.hh"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "transform.hh"
#include "transform_convert.hh"

namespace blender::ed::transform {

/* Resolve the active object's Follow Peg constraint into its rig and (validated) peg index. */
static PegRig *pegrig_active_peg_get(Object *object, int *r_peg_index)
{
  *r_peg_index = -1;
  if (object == nullptr) {
    return nullptr;
  }
  bConstraint *con = BKE_object_find_followpeg_constraint(object);
  if (con == nullptr) {
    return nullptr;
  }
  bFollowPegConstraint *data = static_cast<bFollowPegConstraint *>(con->data);
  if (data->rig == nullptr) {
    return nullptr;
  }
  PegRig *rig = data->rig;
  int obj_peg = data->peg_index;
  if (obj_peg < 0 || obj_peg >= rig->pegs_num ||
      !STREQ(rig->pegs[obj_peg].name, data->peg_name))
  {
    obj_peg = BKE_pegrig_peg_index_by_name(rig, data->peg_name);
  }
  if (obj_peg < 0) {
    return nullptr;
  }

  /* Prefer the rig's active peg when it is the object's own peg or one of its ancestors (the
   * Ctrl+B "climb to parent / Peg Master" navigation); otherwise control the object's own peg. */
  int index = obj_peg;
  const int active = rig->active_peg_index;
  if (active >= 0 && active < rig->pegs_num &&
      (active == obj_peg || BKE_pegrig_peg_is_ancestor(rig, active, obj_peg)))
  {
    index = active;
  }

  *r_peg_index = index;
  return rig;
}

/* World-space pivot of a peg: the point its rotation and scale turn about. It is the parent's world
 * frame applied to (pivot + translation) - the same centre #createTransPegRigPeg measures around and
 * the transform gizmo sits on. */
static void pegrig_peg_pivot_world(const PegRig *rig, int peg_index, float r_center[3])
{
  const PegRigPeg &peg = rig->pegs[peg_index];
  float parent_world[4][4];
  if (peg.parent_index >= 0 && peg.parent_index < rig->pegs_num) {
    BKE_pegrig_peg_compute_world_matrix(rig, peg.parent_index, parent_world);
  }
  else {
    unit_m4(parent_world);
  }
  float pivot_local[3];
  add_v3_v3v3(pivot_local, peg.pivot, peg.translation);
  mul_v3_m4v3(r_center, parent_world, pivot_local);
}

bool transform_pegrig_object_pivot_world(Object *object, float r_pivot[3])
{
  int peg_index;
  PegRig *rig = pegrig_active_peg_get(object, &peg_index);
  if (rig == nullptr) {
    return false;
  }
  pegrig_peg_pivot_world(rig, peg_index, r_pivot);
  return true;
}

bool transform_pegrig_object_axis_world(Object *object, float r_mat[3][3])
{
  int peg_index;
  PegRig *rig = pegrig_active_peg_get(object, &peg_index);
  if (rig == nullptr) {
    return false;
  }
  float peg_to_world[4][4];
  BKE_pegrig_peg_compute_world_matrix(rig, peg_index, peg_to_world);
  copy_m3_m4(r_mat, peg_to_world);
  normalize_m3(r_mat);
  return true;
}

static void createTransPegRigPeg(bContext * /*C*/, TransInfo *t)
{
  BKE_view_layer_synced_ensure(t->scene, t->view_layer);
  Object *object = BKE_view_layer_active_object_get(t->view_layer);
  int peg_index;
  PegRig *rig = pegrig_active_peg_get(object, &peg_index);
  if (rig == nullptr) {
    return;
  }
  PegRigPeg &peg = rig->pegs[peg_index];

  BLI_assert(t->data_container_len == 1);
  TransDataContainer *tc = t->data_container;
  tc->data_len = 1;
  TransData *td = tc->data = MEM_callocN<TransData>(__func__);
  TransDataExtension *td_ext = tc->data_ext = MEM_callocN<TransDataExtension>(__func__);

  /* The peg has no owning object, so its world frame is just its resolved world matrix. */
  float4x4 peg_to_world;
  BKE_pegrig_peg_compute_world_matrix(rig, peg_index, peg_to_world.ptr());
  float4x4 peg_local;
  BKE_pegrig_peg_local_matrix_get(rig, peg_index, peg_local.ptr());

  td->flag = TD_SELECTED;
  td->extra = &rig->id;

  td->loc = peg.translation;
  copy_v3_v3(td->iloc, peg.translation);

  td_ext->rot = peg.rotation;
  td_ext->rotAxis = nullptr;
  td_ext->rotAngle = nullptr;
  td_ext->quat = nullptr;
  copy_v3_v3(td_ext->irot, peg.rotation);
  zero_v3(td_ext->drot);
  td_ext->rotOrder = ROT_MODE_EUL;

  td_ext->scale = peg.scale;
  copy_v3_v3(td_ext->iscale, peg.scale);
  copy_v3_fl(td_ext->dscale, 1.0f);

  /* Rotation and scale happen about the pivot, not the peg's origin. The world centre (parent frame
   * applied to pivot + translation) is the same point the transform gizmo sits on, so the mouse
   * measures the rotation/scale around the visible pivot instead of the peg origin (which is offset
   * from it by the pivot vector). */
  pegrig_peg_pivot_world(rig, peg_index, td->center);

  copy_m3_m4(td->axismtx, peg_to_world.ptr());
  normalize_m3(td->axismtx);

  /* Conversion between the peg's local space and world space (cf. a parented object). */
  float local3[3][3], world3[3][3], world_inv[3][3];
  copy_m3_m4(local3, peg_local.ptr());
  copy_m3_m4(world3, peg_to_world.ptr());
  orthogonalize_m3_zero_axes(local3, 1.0f);
  orthogonalize_m3_zero_axes(world3, 1.0f);
  invert_m3_m3_safe_ortho(world_inv, world3);
  mul_m3_m3m3(td->smtx, local3, world_inv);
  invert_m3_m3_safe_ortho(td->mtx, td->smtx);
}

static void recalcData_pegrig_peg(TransInfo *t)
{
  const TransDataContainer *tc = t->data_container;
  if (tc->data_len == 0 || tc->data == nullptr) {
    return;
  }
  ID *rig_id = static_cast<ID *>(tc->data[0].extra);
  if (rig_id == nullptr) {
    return;
  }
  /* Re-evaluate the rig parameters so every object bound to one of its pegs follows along. */
  DEG_id_tag_update(rig_id, ID_RECALC_PARAMETERS);
}

static void special_aftertrans_update_pegrig_peg(bContext *C, TransInfo *t)
{
  if (t->state == TRANS_CANCEL) {
    return;
  }
  if (!animrig::is_autokey_on(t->scene)) {
    return;
  }
  BKE_view_layer_synced_ensure(t->scene, t->view_layer);
  Object *object = BKE_view_layer_active_object_get(t->view_layer);
  int peg_index;
  PegRig *rig = pegrig_active_peg_get(object, &peg_index);
  if (rig == nullptr) {
    return;
  }
  if (!animrig::autokeyframe_cfra_can_key(t->scene, &rig->id)) {
    return;
  }

  PointerRNA peg_ptr = RNA_pointer_create_discrete(
      &rig->id, &RNA_PegRigPeg, &rig->pegs[peg_index]);
  const float cfra = BKE_scene_frame_get(t->scene);
  /* Key the whole peg pose so cut-out poses have no gaps. */
  for (const char *prop_name : {"translation", "rotation", "scale"}) {
    if (PropertyRNA *prop = RNA_struct_find_property(&peg_ptr, prop_name)) {
      animrig::autokeyframe_property(C, t->scene, &peg_ptr, prop, -1, cfra, false);
    }
  }
}

TransConvertTypeInfo TransConvertType_PegRigPeg = {
    /*flags*/ 0,
    /*create_trans_data*/ createTransPegRigPeg,
    /*recalc_data*/ recalcData_pegrig_peg,
    /*special_aftertrans_update*/ special_aftertrans_update_pegrig_peg,
};

}  // namespace blender::ed::transform
