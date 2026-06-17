/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup bke
 *
 * The Nuclear "peg rig" data-block: a flat array of pegs (transform controllers) whose parenting
 * is expressed by index. See #BKE_pegrig.hh for the public API.
 */

#include <cstring>

#include "MEM_guardedalloc.h"

#include "DNA_constraint_types.h"
#include "DNA_defaults.h"
#include "DNA_object_types.h"
#include "DNA_pegrig_types.h"

#include "BLI_array.hh"
#include "BLI_listbase.h"
#include "BLI_math_matrix.h"
#include "BLI_math_matrix.hh"
#include "BLI_math_vector.h"
#include "BLI_string.h"
#include "BLI_string_utils.hh"
#include "BLI_utildefines.h"

#include "BLT_translation.hh"

#include "BKE_idtype.hh"
#include "BKE_lib_id.hh"
#include "BKE_pegrig.hh"

#include "BLO_read_write.hh"

/* -------------------------------------------------------------------- */
/** \name Data-block lifecycle
 * \{ */

static void pegrig_init_data(ID *id)
{
  PegRig *rig = (PegRig *)id;

  BLI_assert(MEMCMP_STRUCT_AFTER_IS_ZERO(rig, id));

  MEMCPY_STRUCT_AFTER(rig, DNA_struct_default_get(PegRig), id);
}

static void pegrig_copy_data(Main * /*bmain*/,
                             std::optional<Library *> /*owner_library*/,
                             ID *id_dst,
                             const ID *id_src,
                             const int /*flag*/)
{
  PegRig *rig_dst = (PegRig *)id_dst;
  const PegRig *rig_src = (const PegRig *)id_src;

  if (rig_src->pegs != nullptr) {
    rig_dst->pegs = static_cast<PegRigPeg *>(MEM_dupallocN(rig_src->pegs));
  }
}

static void pegrig_free_data(ID *id)
{
  PegRig *rig = (PegRig *)id;
  MEM_SAFE_FREE(rig->pegs);
  /* AnimData (`adt`) is freed by the generic ID code. */
}

static void pegrig_blend_write(BlendWriter *writer, ID *id, const void *id_address)
{
  PegRig *rig = (PegRig *)id;

  BLO_write_id_struct(writer, PegRig, id_address, &rig->id);
  BKE_id_blend_write(writer, &rig->id);

  BLO_write_struct_array(writer, PegRigPeg, rig->pegs_num, rig->pegs);
}

static void pegrig_blend_read_data(BlendDataReader *reader, ID *id)
{
  PegRig *rig = (PegRig *)id;
  BLO_read_struct_array(reader, PegRigPeg, rig->pegs_num, &rig->pegs);
  /* `world_mat` is runtime; it is recomputed by #BKE_pegrig_solve_world_matrices on evaluation. */
}

IDTypeInfo IDType_ID_PG = {
    /*id_code*/ PegRig::id_type,
    /*id_filter*/ FILTER_ID_PG,
    /*dependencies_id_types*/ 0,
    /*main_listbase_index*/ INDEX_ID_PG,
    /*struct_size*/ sizeof(PegRig),
    /*name*/ "PegRig",
    /*name_plural*/ N_("pegrigs"),
    /*translation_context*/ BLT_I18NCONTEXT_ID_ID,
    /*flags*/ IDTYPE_FLAGS_APPEND_IS_REUSABLE,
    /*asset_type_info*/ nullptr,

    /*init_data*/ pegrig_init_data,
    /*copy_data*/ pegrig_copy_data,
    /*free_data*/ pegrig_free_data,
    /*make_local*/ nullptr,
    /*foreach_id*/ nullptr,
    /*foreach_cache*/ nullptr,
    /*foreach_path*/ nullptr,
    /*foreach_working_space_color*/ nullptr,
    /*owner_pointer_get*/ nullptr,

    /*blend_write*/ pegrig_blend_write,
    /*blend_read_data*/ pegrig_blend_read_data,
    /*blend_read_after_liblink*/ nullptr,

    /*blend_read_undo_preserve*/ nullptr,

    /*lib_override_apply_post*/ nullptr,
};

/** \} */

/* -------------------------------------------------------------------- */
/** \name Public API
 * \{ */

PegRig *BKE_pegrig_add(Main *bmain, const char *name)
{
  return BKE_id_new<PegRig>(bmain, name);
}

static bool pegrig_name_in_use(const PegRig *rig, const char *name, const int skip_index)
{
  for (int i = 0; i < rig->pegs_num; i++) {
    if (i == skip_index) {
      continue;
    }
    if (STREQ(rig->pegs[i].name, name)) {
      return true;
    }
  }
  return false;
}

int BKE_pegrig_peg_add(PegRig *rig, const char *name, const int parent_index)
{
  const int new_index = rig->pegs_num;

  /* Grow the array; newly allocated memory is zeroed by MEM_recallocN. */
  rig->pegs = static_cast<PegRigPeg *>(
      MEM_recallocN(rig->pegs, sizeof(PegRigPeg) * (new_index + 1)));
  rig->pegs_num = new_index + 1;

  PegRigPeg *peg = &rig->pegs[new_index];
  copy_v3_fl(peg->scale, 1.0f);
  /* Squash defaults: inert until #PEGRIGPEG_SQUASH is set, but kept non-degenerate (unit vertical
   * axis, full volume preservation) so enabling squash never starts from a zero-length axis. The
   * anchor stays at the origin from the zeroed allocation. */
  peg->squash_tip[1] = 1.0f;
  peg->squash_rest_len = 1.0f;
  peg->squash_volume = 1.0f;
  unit_m4(peg->world_mat);
  peg->parent_index = (parent_index >= 0 && parent_index < new_index) ? parent_index : -1;

  STRNCPY(peg->name, (name != nullptr && name[0] != '\0') ? name : "Peg");
  BLI_uniquename_cb(
      [&](const blender::StringRefNull check) {
        return pegrig_name_in_use(rig, check.c_str(), new_index);
      },
      "Peg",
      '.',
      peg->name,
      sizeof(peg->name));

  return new_index;
}

bool BKE_pegrig_peg_remove(PegRig *rig, const int peg_index)
{
  if (peg_index < 0 || peg_index >= rig->pegs_num) {
    return false;
  }

  /* Fix up parent references: children of the removed peg are reparented to its parent, and any
   * index greater than the removed one shifts down by one. */
  const int removed_parent = rig->pegs[peg_index].parent_index;
  for (int i = 0; i < rig->pegs_num; i++) {
    int *parent = &rig->pegs[i].parent_index;
    if (*parent == peg_index) {
      *parent = (removed_parent > peg_index) ? removed_parent - 1 : removed_parent;
    }
    else if (*parent > peg_index) {
      *parent -= 1;
    }
  }

  /* Shift the tail down over the removed element and shrink the array. */
  const int new_num = rig->pegs_num - 1;
  if (peg_index < new_num) {
    memmove(&rig->pegs[peg_index],
            &rig->pegs[peg_index + 1],
            sizeof(PegRigPeg) * (new_num - peg_index));
  }
  if (new_num == 0) {
    MEM_SAFE_FREE(rig->pegs);
  }
  else {
    rig->pegs = static_cast<PegRigPeg *>(MEM_recallocN(rig->pegs, sizeof(PegRigPeg) * new_num));
  }
  rig->pegs_num = new_num;

  if (rig->active_peg_index == peg_index) {
    rig->active_peg_index = -1;
  }
  else if (rig->active_peg_index > peg_index) {
    rig->active_peg_index -= 1;
  }

  /* Constraints still referencing the removed peg by name resolve to -1 at evaluation time and
   * simply stop following, so no fixup is needed here. */
  return true;
}

int BKE_pegrig_peg_index_by_name(const PegRig *rig, const char *name)
{
  if (name == nullptr) {
    return -1;
  }
  for (int i = 0; i < rig->pegs_num; i++) {
    if (STREQ(rig->pegs[i].name, name)) {
      return i;
    }
  }
  return -1;
}

PegRigPeg *BKE_pegrig_peg_find_by_name(PegRig *rig, const char *name)
{
  const int index = BKE_pegrig_peg_index_by_name(rig, name);
  return (index >= 0) ? &rig->pegs[index] : nullptr;
}

bool BKE_pegrig_peg_is_ancestor(const PegRig *rig, const int ancestor, const int peg)
{
  if (ancestor < 0 || peg < 0 || peg >= rig->pegs_num) {
    return false;
  }
  int p = rig->pegs[peg].parent_index;
  int guard = 0;
  while (p >= 0 && p < rig->pegs_num && guard <= rig->pegs_num) {
    if (p == ancestor) {
      return true;
    }
    p = rig->pegs[p].parent_index;
    guard++;
  }
  return false;
}

bool BKE_pegrig_peg_reparent(PegRig *rig, const int peg_index, const int new_parent_index)
{
  if (peg_index < 0 || peg_index >= rig->pegs_num) {
    return false;
  }
  if (new_parent_index < -1 || new_parent_index >= rig->pegs_num) {
    return false;
  }
  if (new_parent_index == peg_index) {
    return false;
  }
  /* Walk up the prospective parent chain; reaching peg_index would make a cycle. */
  for (int p = new_parent_index; p != -1; p = rig->pegs[p].parent_index) {
    if (p == peg_index) {
      return false;
    }
  }
  rig->pegs[peg_index].parent_index = new_parent_index;
  return true;
}

static void pegrig_peg_local_matrix(const PegRigPeg *peg, float r_mat[4][4])
{
  using namespace blender;
  const float3 pivot(peg->pivot);
  /* Rotate and scale around the pivot, then translate (matches LayerGroup::local_transform). The
   * rotation centre is pivot+translation, so a dragged drawing keeps spinning about itself. */
  float4x4 mat = math::from_loc_rot_scale<float4x4, math::EulerXYZ>(
                     float3(peg->translation) + pivot,
                     float3(peg->rotation),
                     float3(peg->scale)) *
                 math::from_location<float4x4>(-pivot);

  /* Squash & Stretch (see SquashFeature.md): fold a volume-preserving non-uniform scale, anchored
   * in the peg's parent space, on top of the pose. The body scales by `s` along the anchor->tip
   * axis and compensates by `k` in the orthogonal drawing-plane direction so area is preserved.
   * Inert unless the flag is set and the rest length is positive, so a peg without squash yields a
   * byte-identical matrix. The squash is `S * local` (S in parent space) so the anchor stays put
   * regardless of the peg's own pose. */
  if ((peg->flag & PEGRIGPEG_SQUASH) && peg->squash_rest_len > 1e-6f) {
    const float3 anchor(peg->squash_anchor);
    const float3 axis = float3(peg->squash_tip) - anchor;
    const float len = math::length(axis);
    if (len > 1e-6f) {
      const float s = len / peg->squash_rest_len;
      /* volume=0 -> pure axis scale (k=1); volume=1 -> area-preserving (k=1/s). */
      const float k = 1.0f + peg->squash_volume * (1.0f / s - 1.0f);
      const float3 d = axis / len;
      const float3 e(-d.y, d.x, 0.0f); /* perpendicular within the 2D drawing plane (Z unscaled). */

      /* Linear part: I + (s-1) d⊗d + (k-1) e⊗e. Symmetric, so column/row order is irrelevant. */
      float4x4 squash = float4x4::identity();
      for (int i = 0; i < 3; i++) {
        for (int j = 0; j < 3; j++) {
          squash[j][i] += (s - 1.0f) * d[i] * d[j] + (k - 1.0f) * e[i] * e[j];
        }
      }
      /* Translation that keeps `anchor` fixed: t = anchor - linear * anchor. */
      float3 lin_anchor;
      for (int i = 0; i < 3; i++) {
        lin_anchor[i] = squash[0][i] * anchor[0] + squash[1][i] * anchor[1] +
                        squash[2][i] * anchor[2];
      }
      squash[3] = float4(anchor - lin_anchor, 1.0f);

      mat = squash * mat;
    }
  }
  copy_m4_m4(r_mat, mat.ptr());
}

/* Visit state for the topological solve: 0 = unvisited, 1 = in progress, 2 = done. */
static void pegrig_solve_peg(PegRig *rig, const int index, blender::MutableSpan<int8_t> state)
{
  if (state[index] == 2) {
    return;
  }
  PegRigPeg *peg = &rig->pegs[index];
  float local[4][4];
  pegrig_peg_local_matrix(peg, local);

  const int parent = peg->parent_index;
  const bool parent_valid = parent >= 0 && parent < rig->pegs_num && parent != index &&
                            /* state==1 means we looped back to an ancestor: treat as root. */
                            state[parent] != 1;
  if (parent_valid) {
    state[index] = 1;
    pegrig_solve_peg(rig, parent, state);
    mul_m4_m4m4(peg->world_mat, rig->pegs[parent].world_mat, local);
  }
  else {
    copy_m4_m4(peg->world_mat, local);
  }
  state[index] = 2;
}

void BKE_pegrig_solve_world_matrices(PegRig *rig)
{
  if (rig->pegs_num == 0) {
    return;
  }
  blender::Array<int8_t> state(rig->pegs_num, 0);
  for (int i = 0; i < rig->pegs_num; i++) {
    pegrig_solve_peg(rig, i, state);
  }
}

bool BKE_pegrig_peg_world_matrix_get(const PegRig *rig, const int peg_index, float r_mat[4][4])
{
  if (peg_index < 0 || peg_index >= rig->pegs_num) {
    unit_m4(r_mat);
    return false;
  }
  copy_m4_m4(r_mat, rig->pegs[peg_index].world_mat);
  return true;
}

static void pegrig_compute_world_recursive(
    const PegRig *rig, const int index, const int depth, float r_mat[4][4])
{
  float local[4][4];
  pegrig_peg_local_matrix(&rig->pegs[index], local);

  const int parent = rig->pegs[index].parent_index;
  /* `depth` guards against cycles: a valid chain can never exceed `pegs_num` links. */
  if (parent >= 0 && parent < rig->pegs_num && parent != index && depth < rig->pegs_num) {
    float parent_world[4][4];
    pegrig_compute_world_recursive(rig, parent, depth + 1, parent_world);
    mul_m4_m4m4(r_mat, parent_world, local);
  }
  else {
    copy_m4_m4(r_mat, local);
  }
}

bool BKE_pegrig_peg_compute_world_matrix(const PegRig *rig, const int peg_index, float r_mat[4][4])
{
  if (peg_index < 0 || peg_index >= rig->pegs_num) {
    unit_m4(r_mat);
    return false;
  }
  pegrig_compute_world_recursive(rig, peg_index, 0, r_mat);
  return true;
}

bool BKE_pegrig_peg_local_matrix_get(const PegRig *rig, const int peg_index, float r_mat[4][4])
{
  if (peg_index < 0 || peg_index >= rig->pegs_num) {
    unit_m4(r_mat);
    return false;
  }
  pegrig_peg_local_matrix(&rig->pegs[peg_index], r_mat);
  return true;
}

bConstraint *BKE_object_find_followpeg_constraint(const Object *ob)
{
  if (ob == nullptr) {
    return nullptr;
  }
  LISTBASE_FOREACH (bConstraint *, con, &ob->constraints) {
    if (con->type == CONSTRAINT_TYPE_FOLLOWPEG) {
      return con;
    }
  }
  return nullptr;
}

/** \} */
