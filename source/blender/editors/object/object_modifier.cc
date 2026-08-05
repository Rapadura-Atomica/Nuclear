/* SPDX-FileCopyrightText: 2001-2002 NaN Holding BV. All rights reserved.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edobj
 */

#include <cstdio>
#include <cstdlib>

#include "CLG_log.h"

#include "MEM_guardedalloc.h"

#include <algorithm>
#include <limits>

#include "DNA_armature_types.h"
#include "DNA_array_utils.hh"
#include "DNA_constraint_types.h"
#include "DNA_curve_types.h"
#include "DNA_defaults.h"
#include "DNA_grease_pencil_types.h"
#include "DNA_key_types.h"
#include "DNA_lattice_types.h"
#include "DNA_layer_types.h"
#include "DNA_material_types.h"
#include "DNA_mesh_types.h"
#include "DNA_meshdata_types.h"
#include "DNA_object_force_types.h"
#include "DNA_pointcloud_types.h"
#include "DNA_scene_types.h"

#include "BLI_array_utils.hh"
#include "BLI_bitmap.h"
#include "BLI_implicit_sharing.hh"
#include "BLI_listbase.h"
#include "BLI_string.h"
#include "BLI_string_utf8.h"
#include "BLI_string_utils.hh"
#include "BLI_utildefines.h"

#include "BKE_animsys.h"
#include "BKE_anonymous_attribute_id.hh"
#include "BKE_armature.hh"
#include "BKE_context.hh"
#include "BLI_array.hh"
#include "BLI_convexhull_2d.hh"
#include "BLI_math_matrix.h"
#include "BLI_math_matrix.hh"
#include "BLI_math_rotation.h"
#include "BLI_math_vector.hh"
#include "BLI_vector.hh"

#include "BKE_attribute.hh"
#include "BKE_collection.hh"
#include "BKE_curve.hh"

#include "BKE_curves.h"
#include "BKE_curves.hh"
#include "BKE_displist.h"
#include "BKE_editmesh.hh"
#include "BKE_effect.h"
#include "BKE_geometry_set.hh"
#include "BKE_global.hh"
#include "BKE_grease_pencil.hh"
#include "BKE_idprop.hh"
#include "BKE_key.hh"
#include "BKE_lattice.hh"
#include "BKE_layer.hh"
#include "BKE_lib_id.hh"
#include "BKE_library.hh"
#include "BKE_main.hh"
#include "BKE_main_invariants.hh"
#include "BKE_material.hh"
#include "BKE_mball.hh"
#include "BKE_mesh.hh"
#include "BKE_mesh_mapping.hh"
#include "BKE_mesh_runtime.hh"
#include "BKE_modifier.hh"
#include "BKE_multires.hh"
#include "BKE_object.hh"
#include "BKE_object_deform.h"
#include "BKE_object_types.hh"
#include "BKE_ocean.h"
#include "BKE_paint.hh"
#include "BKE_particle.h"
#include "BKE_pointcloud.hh"
#include "BKE_report.hh"
#include "BKE_scene.hh"
#include "BKE_softbody.h"
#include "BKE_volume.hh"
#include "MOD_grease_pencil_contour.hh"
#include "MOD_grease_pencil_curve.hh"

#include "BLT_translation.hh"

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_build.hh"
#include "DEG_depsgraph_query.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"
#include "RNA_enum_types.hh"
#include "RNA_prototypes.hh"

#include "ED_armature.hh"
#include "ED_grease_pencil.hh"
#include "ED_node.hh"
#include "ED_object.hh"
#include "ED_object_vgroup.hh"
#include "ED_screen.hh"

#include "ANIM_bone_collections.hh"

#include "GEO_merge_layers.hh"

#include "UI_interface.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "object_intern.hh"

namespace blender::ed::object {

static CLG_LogRef LOG = {"object"};

static void modifier_skin_customdata_delete(Object *ob);

/* ------------------------------------------------------------------- */
/** \name Public API
 * \{ */

static void object_force_modifier_update_for_bind(Depsgraph *depsgraph, Object *ob)
{
  Scene *scene_eval = DEG_get_evaluated_scene(depsgraph);
  Object *ob_eval = DEG_get_evaluated(depsgraph, ob);
  BKE_object_eval_reset(ob_eval);
  if (ob->type == OB_MESH) {
    Mesh *mesh_eval = blender::bke::mesh_create_eval_final(
        depsgraph, scene_eval, ob_eval, &CD_MASK_DERIVEDMESH);
    BKE_id_free(nullptr, mesh_eval);
  }
  else if (ob->type == OB_LATTICE) {
    BKE_lattice_modifiers_calc(depsgraph, scene_eval, ob_eval);
  }
  else if (ob->type == OB_MBALL) {
    BKE_mball_data_update(depsgraph, scene_eval, ob_eval);
  }
  else if (ELEM(ob->type, OB_CURVES_LEGACY, OB_SURF, OB_FONT)) {
    BKE_displist_make_curveTypes(depsgraph, scene_eval, ob_eval, false);
  }
  else if (ob->type == OB_CURVES) {
    BKE_curves_data_update(depsgraph, scene_eval, ob);
  }
  else if (ob->type == OB_POINTCLOUD) {
    BKE_pointcloud_data_update(depsgraph, scene_eval, ob);
  }
  else if (ob->type == OB_VOLUME) {
    BKE_volume_data_update(depsgraph, scene_eval, ob);
  }
}

static void object_force_modifier_bind_simple_options(Depsgraph *depsgraph,
                                                      Object *object,
                                                      ModifierData *md)
{
  ModifierData *md_eval = BKE_modifier_get_evaluated(depsgraph, object, md);
  const int mode = md_eval->mode;
  md_eval->mode |= eModifierMode_Realtime;
  object_force_modifier_update_for_bind(depsgraph, object);
  md_eval->mode = mode;
}

ModifierData *modifier_add(
    ReportList *reports, Main *bmain, Scene *scene, Object *ob, const char *name, int type)
{
  ModifierData *new_md = nullptr;
  const ModifierTypeInfo *mti = BKE_modifier_get_info((ModifierType)type);

  /* Check compatibility of modifier [#25291, #50373]. */
  if (!BKE_object_support_modifier_type_check(ob, type)) {
    BKE_reportf(reports, RPT_WARNING, "Modifiers cannot be added to object '%s'", ob->id.name + 2);
    return nullptr;
  }

  if (mti->flags & eModifierTypeFlag_Single) {
    if (BKE_modifiers_findby_type(ob, (ModifierType)type)) {
      BKE_report(reports, RPT_WARNING, "Only one modifier of this type is allowed");
      return nullptr;
    }
  }

  if (type == eModifierType_ParticleSystem) {
    /* don't need to worry about the new modifier's name, since that is set to the number
     * of particle systems which shouldn't have too many duplicates
     */
    new_md = object_add_particle_system(bmain, scene, ob, name);
  }
  else {
    /* get new modifier data to add */
    new_md = BKE_modifier_new(type);

    ModifierData *next_md = nullptr;
    LISTBASE_FOREACH_BACKWARD (ModifierData *, md, &ob->modifiers) {
      if (md->flag & eModifierFlag_PinLast) {
        next_md = md;
      }
      else {
        break;
      }
    }
    if (mti->flags & eModifierTypeFlag_RequiresOriginalData) {
      next_md = static_cast<ModifierData *>(ob->modifiers.first);

      while (next_md && BKE_modifier_get_info((ModifierType)next_md->type)->type ==
                            ModifierTypeType::OnlyDeform)
      {
        if (next_md->next && (next_md->next->flag & eModifierFlag_PinLast) != 0) {
          break;
        }
        next_md = next_md->next;
      }
    }
    BLI_insertlinkbefore(&ob->modifiers, next_md, new_md);
    BKE_modifiers_persistent_uid_init(*ob, *new_md);

    if (name) {
      STRNCPY_UTF8(new_md->name, name);
    }

    /* make sure modifier data has unique name */

    BKE_modifier_unique_name(&ob->modifiers, new_md);

    /* special cases */
    if (type == eModifierType_Softbody) {
      if (!ob->soft) {
        ob->soft = sbNew();
        ob->softflag |= OB_SB_GOAL | OB_SB_EDGES;
      }
    }
    else if (type == eModifierType_Collision) {
      if (!ob->pd) {
        ob->pd = BKE_partdeflect_new(0);
      }

      ob->pd->deflect = 1;
    }
    else if (type == eModifierType_Surface) {
      /* pass */
    }
    else if (type == eModifierType_Multires) {
      /* set totlvl from existing MDISPS layer if object already had it */
      multiresModifier_set_levels_from_disps((MultiresModifierData *)new_md, ob);

      if (ob->mode & OB_MODE_SCULPT) {
        /* ensure that grid paint mask layer is created */
        BKE_sculpt_mask_layers_ensure(nullptr, nullptr, ob, (MultiresModifierData *)new_md);
      }
    }
    else if (type == eModifierType_Skin) {
      /* ensure skin-node customdata exists */
      BKE_mesh_ensure_skin_customdata(static_cast<Mesh *>(ob->data));
    }
  }

  BKE_object_modifier_set_active(ob, new_md);

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  DEG_relations_tag_update(bmain);

  return new_md;
}

/* Return true if the object has a modifier of type 'type' other than
 * the modifier pointed to be 'exclude', otherwise returns false. */
static bool object_has_modifier(const Object *ob, const ModifierData *exclude, ModifierType type)
{
  LISTBASE_FOREACH (ModifierData *, md, &ob->modifiers) {
    if ((md != exclude) && (md->type == type)) {
      return true;
    }
  }

  return false;
}

bool iter_other(Main *bmain,
                Object *orig_ob,
                const bool include_orig,
                bool (*callback)(Object *ob, void *callback_data),
                void *callback_data)
{
  ID *ob_data_id = static_cast<ID *>(orig_ob->data);
  int users = ob_data_id->us;

  if (ob_data_id->flag & ID_FLAG_FAKEUSER) {
    users--;
  }

  /* First check that the object's data has multiple users */
  if (users > 1) {
    Object *ob;
    int totfound = include_orig ? 0 : 1;

    for (ob = static_cast<Object *>(bmain->objects.first); ob && totfound < users;
         ob = reinterpret_cast<Object *>(ob->id.next))
    {
      if (((ob != orig_ob) || include_orig) && (ob->data == orig_ob->data)) {
        if (callback(ob, callback_data)) {
          return true;
        }

        totfound++;
      }
    }
  }
  else if (include_orig) {
    return callback(orig_ob, callback_data);
  }

  return false;
}

static bool object_has_modifier_cb(Object *ob, void *data)
{
  ModifierType type = *((ModifierType *)data);

  return object_has_modifier(ob, nullptr, type);
}

bool multires_update_totlevels(Object *ob, void *totlevel_v)
{
  int totlevel = *((char *)totlevel_v);

  LISTBASE_FOREACH (ModifierData *, md, &ob->modifiers) {
    if (md->type == eModifierType_Multires) {
      multires_set_tot_level(ob, (MultiresModifierData *)md, totlevel);
      DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
    }
  }
  return false;
}

/* Return true if no modifier of type 'type' other than 'exclude' */
static bool object_modifier_safe_to_delete(Main *bmain,
                                           Object *ob,
                                           ModifierData *exclude,
                                           ModifierType type)
{
  return (!object_has_modifier(ob, exclude, type) &&
          !iter_other(bmain, ob, false, object_has_modifier_cb, &type));
}

static bool object_modifier_remove(
    Main *bmain, Scene *scene, Object *ob, ModifierData *md, bool *r_sort_depsgraph)
{
  /* It seems on rapid delete it is possible to
   * get called twice on same modifier, so make
   * sure it is in list. */
  if (BLI_findindex(&ob->modifiers, md) == -1) {
    return false;
  }

  /* special cases */
  if (md->type == eModifierType_ParticleSystem) {
    object_remove_particle_system(bmain, scene, ob, ((ParticleSystemModifierData *)md)->psys);
    return true;
  }

  if (md->type == eModifierType_Softbody) {
    if (ob->soft) {
      sbFree(ob);
      ob->softflag = 0; /* TODO(Sybren): this should probably be moved into sbFree() */
    }
  }
  else if (md->type == eModifierType_Collision) {
    if (ob->pd) {
      ob->pd->deflect = 0;
    }

    *r_sort_depsgraph = true;
  }
  else if (md->type == eModifierType_Surface) {
    *r_sort_depsgraph = true;
  }
  else if (md->type == eModifierType_Multires) {
    /* Delete MDisps layer if not used by another multires modifier */
    if (object_modifier_safe_to_delete(bmain, ob, md, eModifierType_Multires)) {
      multires_customdata_delete(static_cast<Mesh *>(ob->data));
    }
  }
  else if (md->type == eModifierType_Skin) {
    /* Delete MVertSkin layer if not used by another skin modifier */
    if (object_modifier_safe_to_delete(bmain, ob, md, eModifierType_Skin)) {
      modifier_skin_customdata_delete(ob);
    }
  }

  if (ELEM(md->type, eModifierType_Softbody, eModifierType_Cloth) &&
      BLI_listbase_is_empty(&ob->particlesystem))
  {
    ob->mode &= ~OB_MODE_PARTICLE_EDIT;
  }

  BKE_animdata_drivers_remove_for_rna_struct(ob->id, RNA_Modifier, md);

  BKE_modifier_remove_from_list(ob, md);
  BKE_modifier_free(md);
  BKE_object_free_derived_caches(ob);

  return true;
}

bool modifier_remove(ReportList *reports, Main *bmain, Scene *scene, Object *ob, ModifierData *md)
{
  bool sort_depsgraph = false;

  bool ok = object_modifier_remove(bmain, scene, ob, md, &sort_depsgraph);

  if (!ok) {
    BKE_reportf(reports, RPT_ERROR, "Modifier '%s' not in object '%s'", md->name, ob->id.name);
    return false;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  DEG_relations_tag_update(bmain);

  return true;
}

void modifiers_clear(Main *bmain, Scene *scene, Object *ob)
{
  ModifierData *md = static_cast<ModifierData *>(ob->modifiers.first);
  bool sort_depsgraph = false;

  if (!md) {
    return;
  }

  while (md) {
    ModifierData *next_md = md->next;

    object_modifier_remove(bmain, scene, ob, md, &sort_depsgraph);

    md = next_md;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  DEG_relations_tag_update(bmain);
}

static bool object_modifier_check_move_before(ReportList *reports,
                                              eReportType error_type,
                                              ModifierData *md,
                                              ModifierData *md_prev)
{
  if (md_prev) {
    if (md->flag & eModifierFlag_PinLast && !(md_prev->flag & eModifierFlag_PinLast)) {
      return false;
    }
    const ModifierTypeInfo *mti = BKE_modifier_get_info((ModifierType)md->type);

    if (mti->type != ModifierTypeType::OnlyDeform) {
      const ModifierTypeInfo *nmti = BKE_modifier_get_info((ModifierType)md_prev->type);

      if (nmti->flags & eModifierTypeFlag_RequiresOriginalData) {
        BKE_report(reports, error_type, "Cannot move above a modifier requiring original data");
        return false;
      }
    }
  }
  else {
    BKE_report(reports, error_type, "Cannot move modifier beyond the start of the list");
    return false;
  }

  return true;
}

bool modifier_move_up(ReportList *reports, eReportType error_type, Object *ob, ModifierData *md)
{
  if (object_modifier_check_move_before(reports, error_type, md, md->prev)) {
    BLI_listbase_swaplinks(&ob->modifiers, md, md->prev);
    return true;
  }

  return false;
}

static bool object_modifier_check_move_after(ReportList *reports,
                                             eReportType error_type,
                                             ModifierData *md,
                                             ModifierData *md_next)
{
  if (md_next) {
    if (md_next->flag & eModifierFlag_PinLast && !(md->flag & eModifierFlag_PinLast)) {
      return false;
    }
    const ModifierTypeInfo *mti = BKE_modifier_get_info((ModifierType)md->type);

    if (mti->flags & eModifierTypeFlag_RequiresOriginalData) {
      const ModifierTypeInfo *nmti = BKE_modifier_get_info((ModifierType)md_next->type);

      if (nmti->type != ModifierTypeType::OnlyDeform) {
        BKE_report(reports, error_type, "Cannot move beyond a non-deforming modifier");
        return false;
      }
    }
  }
  else {
    BKE_report(reports, error_type, "Cannot move modifier beyond the end of the list");
    return false;
  }

  return true;
}

bool modifier_move_down(ReportList *reports, eReportType error_type, Object *ob, ModifierData *md)
{
  if (object_modifier_check_move_after(reports, error_type, md, md->next)) {
    BLI_listbase_swaplinks(&ob->modifiers, md, md->next);
    return true;
  }

  return false;
}

bool modifier_move_to_index(ReportList *reports,
                            eReportType error_type,
                            Object *ob,
                            ModifierData *md,
                            const int index,
                            bool allow_partial)
{
  BLI_assert(md != nullptr);

  if (index < 0 || index >= BLI_listbase_count(&ob->modifiers)) {
    BKE_report(reports, error_type, "Cannot move modifier beyond the end of the stack");
    return false;
  }

  int md_index = BLI_findindex(&ob->modifiers, md);
  BLI_assert(md_index != -1);

  if (md_index < index) {
    /* Move modifier down in list. */
    ModifierData *md_target = md;

    for (; md_index < index; md_index++, md_target = md_target->next) {
      if (!object_modifier_check_move_after(reports, error_type, md, md_target->next)) {
        if (!allow_partial || md == md_target) {
          return false;
        }

        break;
      }
    }

    BLI_assert(md != md_target && md_target);

    BLI_remlink(&ob->modifiers, md);
    BLI_insertlinkafter(&ob->modifiers, md_target, md);
  }
  else if (md_index > index) {
    /* Move modifier up in list. */
    ModifierData *md_target = md;

    for (; md_index > index; md_index--, md_target = md_target->prev) {
      if (!object_modifier_check_move_before(reports, error_type, md, md_target->prev)) {
        if (!allow_partial || md == md_target) {
          return false;
        }

        break;
      }
    }

    BLI_assert(md != md_target && md_target);

    BLI_remlink(&ob->modifiers, md);
    BLI_insertlinkbefore(&ob->modifiers, md_target, md);
  }
  else {
    return true;
  }

  /* NOTE: Dependency graph only uses modifier nodes for visibility updates, and exact order of
   * modifier nodes in the graph does not matter. */

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_main_add_notifier(NC_OBJECT | ND_MODIFIER, ob);

  return true;
}

void modifier_link(bContext *C, Object *ob_dst, Object *ob_src)
{
  BKE_object_link_modifiers(ob_dst, ob_src);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob_dst);
  DEG_id_tag_update(&ob_dst->id, ID_RECALC_TRANSFORM | ID_RECALC_GEOMETRY | ID_RECALC_ANIMATION);

  Main *bmain = CTX_data_main(C);
  DEG_relations_tag_update(bmain);
}

bool modifier_copy_to_object(Main *bmain,
                             const Scene *scene,
                             const Object *ob_src,
                             const ModifierData *md,
                             Object *ob_dst,
                             ReportList *reports)
{
  const ModifierTypeInfo *mti = BKE_modifier_get_info((ModifierType)md->type);

  BLI_assert(ob_src != ob_dst);

  /* Checked in #BKE_object_copy_modifier, but check here too so we can give a better message. */
  if (!BKE_object_support_modifier_type_check(ob_dst, md->type)) {
    BKE_reportf(reports,
                RPT_WARNING,
                "Object '%s' does not support %s modifiers",
                ob_dst->id.name + 2,
                RPT_(mti->name));
    return false;
  }

  if (mti->flags & eModifierTypeFlag_Single) {
    if (BKE_modifiers_findby_type(ob_dst, (ModifierType)md->type)) {
      BKE_reportf(reports,
                  RPT_WARNING,
                  "Modifier can only be added once to object '%s'",
                  ob_dst->id.name + 2);
      return false;
    }
  }

  if (!BKE_object_copy_modifier(bmain, scene, ob_dst, ob_src, md)) {
    BKE_reportf(reports,
                RPT_ERROR,
                "Copying modifier '%s' to object '%s' failed",
                md->name,
                ob_dst->id.name + 2);
    return false;
  }

  WM_main_add_notifier(NC_OBJECT | ND_MODIFIER | NA_ADDED, ob_dst);
  DEG_id_tag_update(&ob_dst->id, ID_RECALC_GEOMETRY | ID_RECALC_ANIMATION);
  DEG_relations_tag_update(bmain);
  return true;
}

bool convert_psys_to_mesh(ReportList * /*reports*/,
                          Main *bmain,
                          Depsgraph *depsgraph,
                          Scene *scene,
                          ViewLayer *view_layer,
                          Object *ob,
                          ModifierData *md)
{
  int cvert = 0;

  if (md->type != eModifierType_ParticleSystem) {
    return false;
  }
  if (ob && ob->mode & OB_MODE_PARTICLE_EDIT) {
    return false;
  }

  ParticleSystem *psys_orig = ((ParticleSystemModifierData *)md)->psys;
  ParticleSettings *part = psys_orig->part;

  if (part->ren_as != PART_DRAW_PATH) {
    return false;
  }
  ParticleSystem *psys_eval = psys_eval_get(depsgraph, ob, psys_orig);
  if (psys_eval->pathcache == nullptr) {
    return false;
  }

  int part_num = psys_eval->totcached;
  int child_num = psys_eval->totchildcache;

  if (child_num && (part->draw & PART_DRAW_PARENT) == 0) {
    part_num = 0;
  }

  /* count */
  int verts_num = 0, edges_num = 0;
  ParticleCacheKey **cache = psys_eval->pathcache;
  for (int a = 0; a < part_num; a++) {
    ParticleCacheKey *key = cache[a];

    if (key->segments > 0) {
      verts_num += key->segments + 1;
      edges_num += key->segments;
    }
  }

  cache = psys_eval->childcache;
  for (int a = 0; a < child_num; a++) {
    ParticleCacheKey *key = cache[a];

    if (key->segments > 0) {
      verts_num += key->segments + 1;
      edges_num += key->segments;
    }
  }

  if (verts_num == 0) {
    return false;
  }

  Mesh *mesh = BKE_mesh_new_nomain(verts_num, edges_num, 0, 0);
  MutableSpan<float3> positions = mesh->vert_positions_for_write();
  MutableSpan<int2> edges = mesh->edges_for_write();

  bke::MutableAttributeAccessor attributes = mesh->attributes_for_write();
  bke::SpanAttributeWriter<bool> select_vert = attributes.lookup_or_add_for_write_span<bool>(
      ".select_vert", bke::AttrDomain::Point);

  int edge_index = 0;

  /* copy coordinates */
  int vert_index = 0;
  cache = psys_eval->pathcache;
  for (int a = 0; a < part_num; a++) {
    ParticleCacheKey *key = cache[a];
    int kmax = key->segments;
    for (int k = 0; k <= kmax; k++, key++, cvert++, vert_index++) {
      positions[vert_index] = key->co;
      if (k) {
        edges[edge_index] = int2(cvert - 1, cvert);
        edge_index++;
      }
      else {
        /* cheap trick to select the roots */
        select_vert.span[vert_index] = true;
      }
    }
  }

  cache = psys_eval->childcache;
  for (int a = 0; a < child_num; a++) {
    ParticleCacheKey *key = cache[a];
    int kmax = key->segments;
    for (int k = 0; k <= kmax; k++, key++, cvert++, vert_index++) {
      copy_v3_v3(positions[vert_index], key->co);
      if (k) {
        edges[edge_index] = int2(cvert - 1, cvert);
        edge_index++;
      }
      else {
        /* cheap trick to select the roots */
        select_vert.span[vert_index] = true;
      }
    }
  }

  select_vert.finish();

  Object *obn = BKE_object_add(bmain, scene, view_layer, OB_MESH, nullptr);
  BKE_mesh_nomain_to_mesh(mesh, static_cast<Mesh *>(obn->data), obn);

  DEG_relations_tag_update(bmain);

  return true;
}

static void add_shapekey_layers(Mesh &mesh_dest, const Mesh &mesh_src)
{
  if (!mesh_src.key) {
    return;
  }
  int i;
  LISTBASE_FOREACH_INDEX (const KeyBlock *, kb, &mesh_src.key->block, i) {
    void *array;
    if (mesh_src.verts_num != kb->totelem) {
      CLOG_ERROR(&LOG,
                 "vertex size mismatch (Mesh '%s':%d != KeyBlock '%s':%d)",
                 mesh_src.id.name + 2,
                 mesh_src.verts_num,
                 kb->name,
                 kb->totelem);
      array = MEM_calloc_arrayN<float[3]>(mesh_src.verts_num, __func__);
    }
    else {
      array = MEM_malloc_arrayN<float[3]>(size_t(mesh_src.verts_num), __func__);
      memcpy(array, kb->data, sizeof(float[3]) * size_t(mesh_src.verts_num));
    }

    CustomData_add_layer_with_data(
        &mesh_dest.vert_data, CD_SHAPEKEY, array, mesh_dest.verts_num, nullptr);
    const int ci = CustomData_get_layer_index_n(&mesh_dest.vert_data, CD_SHAPEKEY, i);

    mesh_dest.vert_data.layers[ci].uid = kb->uid;
  }
}

/**
 * \param use_virtual_modifiers: When enabled, calculate virtual-modifiers before applying
 * `md_eval`. This is supported because virtual-modifiers are not modifiers from a user
 * perspective, allowing shape keys to be included with the modifier being applied, see: #91923.
 */
static Mesh *create_applied_mesh_for_modifier(Depsgraph *depsgraph,
                                              Scene *scene,
                                              Object *ob_eval,
                                              ModifierData *md_eval,
                                              const bool use_virtual_modifiers,
                                              const bool build_shapekey_layers,
                                              ReportList *reports)
{
  Mesh *mesh = ob_eval->runtime->data_orig ?
                   reinterpret_cast<Mesh *>(ob_eval->runtime->data_orig) :
                   reinterpret_cast<Mesh *>(ob_eval->data);
  const ModifierTypeInfo *mti = BKE_modifier_get_info(ModifierType(md_eval->type));
  const ModifierEvalContext mectx = {depsgraph, ob_eval, MOD_APPLY_TO_ORIGINAL};

  if (!(md_eval->mode & eModifierMode_Realtime)) {
    return nullptr;
  }

  if (mti->is_disabled && mti->is_disabled(scene, md_eval, false)) {
    return nullptr;
  }

  if (build_shapekey_layers && mesh->key) {
    if (KeyBlock *kb = static_cast<KeyBlock *>(
            BLI_findlink(&mesh->key->block, ob_eval->shapenr - 1)))
    {
      BKE_keyblock_convert_to_mesh(kb, mesh->vert_positions_for_write());
    }
  }

  Mesh *mesh_temp = reinterpret_cast<Mesh *>(
      BKE_id_copy_ex(nullptr, &mesh->id, nullptr, LIB_ID_COPY_LOCALIZE));
  MutableSpan<float3> deformedVerts = mesh_temp->vert_positions_for_write();

  if (use_virtual_modifiers) {
    VirtualModifierData virtual_modifier_data;
    for (ModifierData *md_eval_virt =
             BKE_modifiers_get_virtual_modifierlist(ob_eval, &virtual_modifier_data);
         md_eval_virt && (md_eval_virt != ob_eval->modifiers.first);
         md_eval_virt = md_eval_virt->next)
    {
      if (!BKE_modifier_is_enabled(scene, md_eval_virt, eModifierMode_Realtime)) {
        continue;
      }
      /* All virtual modifiers are deform modifiers. */
      const ModifierTypeInfo *mti_virt = BKE_modifier_get_info(ModifierType(md_eval_virt->type));
      BLI_assert(mti_virt->type == ModifierTypeType::OnlyDeform);
      if (mti_virt->type != ModifierTypeType::OnlyDeform) {
        continue;
      }

      mti_virt->deform_verts(md_eval_virt, &mectx, mesh_temp, deformedVerts);
    }
  }

  Mesh *result = nullptr;
  if (mti->type == ModifierTypeType::OnlyDeform) {
    result = mesh_temp;
    mti->deform_verts(md_eval, &mectx, result, deformedVerts);
    result->tag_positions_changed();

    if (build_shapekey_layers) {
      add_shapekey_layers(*result, *mesh);
    }
  }
  else {
    if (build_shapekey_layers) {
      add_shapekey_layers(*mesh_temp, *mesh);
    }

    if (mti->modify_geometry_set) {
      bke::GeometrySet geometry_set = bke::GeometrySet::from_mesh(
          mesh_temp, bke::GeometryOwnershipType::Owned);
      mti->modify_geometry_set(md_eval, &mectx, &geometry_set);
      if (!geometry_set.has_mesh()) {
        BKE_report(reports, RPT_ERROR, "Evaluated geometry from modifier does not contain a mesh");
        return nullptr;
      }
      result = geometry_set.get_component_for_write<bke::MeshComponent>().release();
    }
    else {
      result = mti->modify_mesh(md_eval, &mectx, mesh_temp);
      if (mesh_temp != result) {
        BKE_id_free(nullptr, mesh_temp);
      }
    }
  }

  return result;
}

static bool modifier_apply_shape(Main *bmain,
                                 ReportList *reports,
                                 Depsgraph *depsgraph,
                                 Scene *scene,
                                 Object *ob,
                                 ModifierData *md_eval)
{
  const ModifierTypeInfo *mti = BKE_modifier_get_info((ModifierType)md_eval->type);

  if (mti->is_disabled && mti->is_disabled(scene, md_eval, false)) {
    BKE_report(reports, RPT_ERROR, "Modifier is disabled, skipping apply");
    return false;
  }

  /* We could investigate using the #CD_ORIGINDEX layer
   * to support other kinds of modifiers besides deforming modifiers.
   * as this is done in many other places, see: #BKE_mesh_foreach_mapped_vert_coords_get.
   *
   * This isn't high priority in practice since most modifiers users
   * want to apply as a shape are deforming modifiers.
   *
   * If a compelling use-case comes up where we want to support other kinds of modifiers
   * we can look into supporting them. */

  if (ob->type == OB_MESH) {
    Mesh *mesh = static_cast<Mesh *>(ob->data);
    Key *key = mesh->key;

    if (!BKE_modifier_is_same_topology(md_eval) || mti->type == ModifierTypeType::NonGeometrical) {
      BKE_report(reports, RPT_ERROR, "Only deforming modifiers can be applied to shapes");
      return false;
    }

    Mesh *mesh_applied = create_applied_mesh_for_modifier(depsgraph,
                                                          DEG_get_evaluated_scene(depsgraph),
                                                          DEG_get_evaluated(depsgraph, ob),
                                                          md_eval,
                                                          true,
                                                          false,
                                                          reports);
    if (!mesh_applied) {
      BKE_report(reports, RPT_ERROR, "Modifier is disabled or returned error, skipping apply");
      return false;
    }

    if (key == nullptr) {
      key = mesh->key = BKE_key_add(bmain, (ID *)mesh);
      key->type = KEY_RELATIVE;
      /* if that was the first key block added, then it was the basis.
       * Initialize it with the mesh, and add another for the modifier */
      KeyBlock *kb = BKE_keyblock_add(key, nullptr);
      BKE_keyblock_convert_from_mesh(mesh, key, kb);
    }

    KeyBlock *kb = BKE_keyblock_add(key, md_eval->name);
    BKE_mesh_nomain_to_meshkey(mesh_applied, mesh, kb);

    BKE_id_free(nullptr, mesh_applied);
  }
  else {
    BKE_report(reports, RPT_ERROR, "Cannot apply modifier for this object type");
    return false;
  }
  return true;
}

static bool apply_grease_pencil_for_modifier(Depsgraph *depsgraph,
                                             Object *ob,
                                             GreasePencil &grease_pencil_orig,
                                             ModifierData *md_eval)
{
  using namespace bke;
  using namespace bke::greasepencil;
  const ModifierTypeInfo *mti = BKE_modifier_get_info(ModifierType(md_eval->type));
  Object *ob_eval = DEG_get_evaluated(depsgraph, ob);
  GreasePencil *grease_pencil_for_eval = ob_eval->runtime->data_orig ?
                                             reinterpret_cast<GreasePencil *>(
                                                 ob_eval->runtime->data_orig) :
                                             &grease_pencil_orig;
  const int eval_frame = int(DEG_get_ctime(depsgraph));
  GreasePencil *grease_pencil_temp = reinterpret_cast<GreasePencil *>(
      BKE_id_copy_ex(nullptr, &grease_pencil_for_eval->id, nullptr, LIB_ID_COPY_LOCALIZE));
  grease_pencil_temp->runtime->eval_frame = eval_frame;
  GeometrySet eval_geometry_set = GeometrySet::from_grease_pencil(grease_pencil_temp,
                                                                  GeometryOwnershipType::Owned);

  ModifierEvalContext mectx = {depsgraph, ob_eval, MOD_APPLY_TO_ORIGINAL};
  mti->modify_geometry_set(md_eval, &mectx, &eval_geometry_set);
  if (!eval_geometry_set.has_grease_pencil()) {

    return false;
  }
  GreasePencil &grease_pencil_result =
      *eval_geometry_set.get_component_for_write<GreasePencilComponent>().get_for_write();

  ed::greasepencil::apply_eval_grease_pencil_data(grease_pencil_result,
                                                  eval_frame,
                                                  grease_pencil_orig.layers().index_range(),
                                                  grease_pencil_orig);

  Main *bmain = DEG_get_bmain(depsgraph);
  /* There might be layers with empty names after evaluation. Make sure to rename them. */
  bke::greasepencil::ensure_non_empty_layer_names(*bmain, grease_pencil_result);
  BKE_object_material_from_eval_data(bmain, ob, &grease_pencil_result.id);
  return true;
}

static bool apply_grease_pencil_for_modifier_all_keyframes(Depsgraph *depsgraph,
                                                           Scene *scene,
                                                           Object *ob,
                                                           GreasePencil &grease_pencil_orig,
                                                           ModifierData *md)
{
  using namespace bke;
  using namespace bke::greasepencil;
  Main *bmain = DEG_get_bmain(depsgraph);

  const ModifierTypeInfo *mti = BKE_modifier_get_info(ModifierType(md->type));

  WM_cursor_wait(true);

  Map<int, Vector<int>> layer_indices_to_apply_per_frame;
  {
    for (const int layer_i : grease_pencil_orig.layers().index_range()) {
      const Layer &layer = grease_pencil_orig.layer(layer_i);
      for (const auto &[key, value] : layer.frames().items()) {
        if (value.is_end()) {
          continue;
        }
        layer_indices_to_apply_per_frame.lookup_or_add(key, {}).append(layer_i);
      }
    }
  }

  Array<int> sorted_frame_times(layer_indices_to_apply_per_frame.size());
  int i = 0;
  for (const int key : layer_indices_to_apply_per_frame.keys()) {
    sorted_frame_times[i++] = key;
  }
  std::sort(sorted_frame_times.begin(), sorted_frame_times.end());

  const int prev_frame = int(DEG_get_ctime(depsgraph));
  bool changed = false;
  for (const int eval_frame : sorted_frame_times) {
    const Span<int> layer_indices = layer_indices_to_apply_per_frame.lookup(eval_frame).as_span();
    scene->r.cfra = eval_frame;
    BKE_scene_graph_update_for_newframe(depsgraph);

    Object *ob_eval = DEG_get_evaluated(depsgraph, ob);
    GreasePencil *grease_pencil_for_eval = ob_eval->runtime->data_orig ?
                                               reinterpret_cast<GreasePencil *>(
                                                   ob_eval->runtime->data_orig) :
                                               &grease_pencil_orig;

    GreasePencil *grease_pencil_temp = reinterpret_cast<GreasePencil *>(
        BKE_id_copy_ex(nullptr, &grease_pencil_for_eval->id, nullptr, LIB_ID_COPY_LOCALIZE));
    grease_pencil_temp->runtime->eval_frame = eval_frame;
    GeometrySet eval_geometry_set = GeometrySet::from_grease_pencil(grease_pencil_temp,
                                                                    GeometryOwnershipType::Owned);

    ModifierData *md_eval = BKE_modifier_get_evaluated(depsgraph, ob, md);
    ModifierEvalContext mectx = {depsgraph, ob_eval, MOD_APPLY_TO_ORIGINAL};
    mti->modify_geometry_set(md_eval, &mectx, &eval_geometry_set);
    if (!eval_geometry_set.has_grease_pencil()) {
      continue;
    }
    GreasePencil &grease_pencil_result =
        *eval_geometry_set.get_component_for_write<GreasePencilComponent>().get_for_write();

    IndexMaskMemory memory;
    const IndexMask orig_layers_to_apply = IndexMask::from_indices(layer_indices, memory);
    ed::greasepencil::apply_eval_grease_pencil_data(
        grease_pencil_result, eval_frame, orig_layers_to_apply, grease_pencil_orig);

    BKE_object_material_from_eval_data(bmain, ob, &grease_pencil_result.id);
    changed = true;
  }

  scene->r.cfra = prev_frame;
  BKE_scene_graph_update_for_newframe(depsgraph);

  /* There might be layers with empty names after evaluation. Make sure to rename them. */
  bke::greasepencil::ensure_non_empty_layer_names(*bmain, grease_pencil_orig);

  WM_cursor_wait(false);
  return changed;
}

static bool modifier_apply_obdata(ReportList *reports,
                                  Depsgraph *depsgraph,
                                  Scene *scene,
                                  Object *ob,
                                  ModifierData *md_eval,
                                  const bool do_all_keyframes)
{
  const ModifierTypeInfo *mti = BKE_modifier_get_info((ModifierType)md_eval->type);

  if (mti->is_disabled && mti->is_disabled(scene, md_eval, false)) {
    BKE_report(reports, RPT_ERROR, "Modifier is disabled, skipping apply");
    return false;
  }

  if (ob->type == OB_MESH) {
    Mesh *mesh = static_cast<Mesh *>(ob->data);
    MultiresModifierData *mmd = find_multires_modifier_before(scene, md_eval);

    if (mesh->key && mti->type != ModifierTypeType::NonGeometrical) {
      BKE_report(reports, RPT_ERROR, "Modifier cannot be applied to a mesh with shape keys");
      return false;
    }

    /* Multires: ensure that recent sculpting is applied */
    if (md_eval->type == eModifierType_Multires) {
      multires_force_sculpt_rebuild(ob);
    }

    if (mmd && mmd->totlvl &&
        (mti->type == ModifierTypeType::OnlyDeform || md_eval->type == eModifierType_Nodes))
    {
      if (!multiresModifier_reshapeFromDeformModifier(depsgraph, ob, mmd, md_eval)) {
        BKE_report(reports, RPT_ERROR, "Multires modifier returned error, skipping apply");
        return false;
      }
    }
    else {
      Mesh *mesh_applied = create_applied_mesh_for_modifier(
          depsgraph,
          DEG_get_evaluated_scene(depsgraph),
          DEG_get_evaluated(depsgraph, ob),
          md_eval,
          /* It's important not to apply virtual modifiers (e.g. shape-keys) because they're kept,
           * causing them to be applied twice, see: #97758. */
          false,
          true,
          reports);
      if (!mesh_applied) {
        return false;
      }

      Main *bmain = DEG_get_bmain(depsgraph);
      BKE_object_material_from_eval_data(bmain, ob, &mesh_applied->id);
      BKE_mesh_nomain_to_mesh(mesh_applied, mesh, ob);

      /* Anonymous attributes shouldn't be available on the applied geometry. */
      mesh->attributes_for_write().remove_anonymous();

      /* Remove strings referring to attributes if they no longer exist. */
      bke::mesh_remove_invalid_attribute_strings(*mesh);

      if (md_eval->type == eModifierType_Multires) {
        multires_customdata_delete(mesh);
      }
    }
  }
  else if (ELEM(ob->type, OB_CURVES_LEGACY, OB_SURF)) {
    Object *object_eval = DEG_get_evaluated(depsgraph, ob);
    Curve *curve = static_cast<Curve *>(ob->data);
    Curve *curve_eval = static_cast<Curve *>(object_eval->data);
    ModifierEvalContext mectx = {depsgraph, object_eval, MOD_APPLY_TO_ORIGINAL};

    if (ELEM(mti->type, ModifierTypeType::Constructive, ModifierTypeType::Nonconstructive)) {
      BKE_report(
          reports,
          RPT_ERROR,
          "Cannot apply constructive modifiers on curve. Convert curve to mesh in order to apply");
      return false;
    }

    BKE_report(reports,
               RPT_INFO,
               "Applied modifier only changed CV points, not tessellated/bevel vertices");

    Array<float3> vertexCos = BKE_curve_nurbs_vert_coords_alloc(&curve_eval->nurb);
    mti->deform_verts(md_eval, &mectx, nullptr, vertexCos);
    BKE_curve_nurbs_vert_coords_apply(&curve->nurb, vertexCos, false);

    DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  }
  else if (ob->type == OB_LATTICE) {
    Object *object_eval = DEG_get_evaluated(depsgraph, ob);
    Lattice *lattice = static_cast<Lattice *>(ob->data);
    ModifierEvalContext mectx = {depsgraph, object_eval, MOD_APPLY_TO_ORIGINAL};

    if (ELEM(mti->type, ModifierTypeType::Constructive, ModifierTypeType::Nonconstructive)) {
      BKE_report(reports, RPT_ERROR, "Constructive modifiers cannot be applied");
      return false;
    }

    Array<float3> positions = BKE_lattice_vert_coords_alloc(lattice);
    mti->deform_verts(md_eval, &mectx, nullptr, positions);
    BKE_lattice_vert_coords_apply(lattice, positions);

    DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  }
  else if (ob->type == OB_CURVES) {
    Curves &curves = *static_cast<Curves *>(ob->data);
    if (mti->modify_geometry_set == nullptr) {
      BLI_assert_unreachable();
      return false;
    }

    bke::GeometrySet geometry_set = bke::GeometrySet::from_curves(
        &curves, bke::GeometryOwnershipType::ReadOnly);

    ModifierEvalContext mectx = {depsgraph, ob, MOD_APPLY_TO_ORIGINAL};
    mti->modify_geometry_set(md_eval, &mectx, &geometry_set);
    if (!geometry_set.has_curves()) {
      BKE_report(reports, RPT_ERROR, "Evaluated geometry from modifier does not contain curves");
      return false;
    }
    Curves &curves_eval = *geometry_set.get_curves_for_write();

    /* Anonymous attributes shouldn't be available on original geometry. */
    curves_eval.geometry.wrap().attributes_for_write().remove_anonymous();

    curves.geometry.wrap() = std::move(curves_eval.geometry.wrap());
    Main *bmain = DEG_get_bmain(depsgraph);
    BKE_object_material_from_eval_data(bmain, ob, &curves_eval.id);
  }
  else if (ob->type == OB_POINTCLOUD) {
    PointCloud &points = *static_cast<PointCloud *>(ob->data);
    if (mti->modify_geometry_set == nullptr) {
      BLI_assert_unreachable();
      return false;
    }

    bke::GeometrySet geometry_set = bke::GeometrySet::from_pointcloud(
        BKE_pointcloud_copy_for_eval(&points));

    ModifierEvalContext mectx = {depsgraph, ob, MOD_APPLY_TO_ORIGINAL};
    mti->modify_geometry_set(md_eval, &mectx, &geometry_set);
    if (!geometry_set.has_pointcloud()) {
      BKE_report(
          reports, RPT_ERROR, "Evaluated geometry from modifier does not contain a point cloud");
      return false;
    }
    PointCloud *pointcloud_eval =
        geometry_set.get_component_for_write<bke::PointCloudComponent>().release();

    /* Anonymous attributes shouldn't be available on original geometry. */
    pointcloud_eval->attributes_for_write().remove_anonymous();

    Main *bmain = DEG_get_bmain(depsgraph);
    BKE_object_material_from_eval_data(bmain, ob, &pointcloud_eval->id);
    BKE_pointcloud_nomain_to_pointcloud(pointcloud_eval, &points);
  }
  else if (ob->type == OB_GREASE_PENCIL) {
    if (mti->modify_geometry_set == nullptr) {
      BKE_report(reports, RPT_ERROR, "Cannot apply this modifier to Grease Pencil geometry");
      return false;
    }
    GreasePencil &grease_pencil_orig = *static_cast<GreasePencil *>(ob->data);
    bool success = false;
    if (do_all_keyframes) {
      /* The function #apply_grease_pencil_for_modifier_all_keyframes will retrieve
       * the evaluated modifier for each keyframe. The original modifier is passed
       * to ensure the evaluated modifier is not used, as it will be invalid when
       * the scene graph is updated for the next keyframe. */
      ModifierData *md = BKE_modifier_get_original(ob, md_eval);
      success = apply_grease_pencil_for_modifier_all_keyframes(
          depsgraph, scene, ob, grease_pencil_orig, md);
    }
    else {
      success = apply_grease_pencil_for_modifier(depsgraph, ob, grease_pencil_orig, md_eval);
    }
    if (!success) {
      BKE_report(reports,
                 RPT_ERROR,
                 "Evaluated geometry from modifier does not contain Grease Pencil geometry");
      return false;
    }
  }
  else {
    /* TODO: implement for volumes. */
    BKE_report(reports, RPT_ERROR, "Cannot apply modifier for this object type");
    return false;
  }

  /* lattice modifier can be applied to particle system too */
  if (ob->particlesystem.first) {
    LISTBASE_FOREACH (ParticleSystem *, psys, &ob->particlesystem) {
      if (psys->part->type != PART_HAIR) {
        continue;
      }

      psys_apply_hair_lattice(depsgraph, scene, ob, psys);
    }
  }

  return true;
}

bool modifier_apply(Main *bmain,
                    ReportList *reports,
                    Depsgraph *depsgraph,
                    Scene *scene,
                    Object *ob,
                    ModifierData *md,
                    int mode,
                    bool keep_modifier,
                    const bool do_all_keyframes)
{
  if (BKE_object_is_in_editmode(ob)) {
    BKE_report(reports, RPT_ERROR, "Modifiers cannot be applied in edit mode");
    return false;
  }
  if (mode != MODIFIER_APPLY_SHAPE && ID_REAL_USERS(ob->data) > 1) {
    BKE_report(reports, RPT_ERROR, "Modifiers cannot be applied to multi-user data");
    return false;
  }
  if ((ob->mode & OB_MODE_SCULPT) && find_multires_modifier_before(scene, md) &&
      (BKE_modifier_is_same_topology(md) == false))
  {
    BKE_report(reports,
               RPT_ERROR,
               "Constructive modifier cannot be applied to multi-res data in sculpt mode");
    return false;
  }

  if (md != ob->modifiers.first) {
    BKE_report(reports, RPT_INFO, "Applied modifier was not first, result may not be as expected");
  }

  /* Get evaluated modifier, so object links pointer to evaluated data,
   * but still use original object it is applied to the original mesh. */
  Object *ob_eval = DEG_get_evaluated(depsgraph, ob);
  ModifierData *md_eval = (ob_eval) ? BKE_modifiers_findby_name(ob_eval, md->name) : md;

  Depsgraph *apply_depsgraph = depsgraph;
  Depsgraph *local_depsgraph = nullptr;

  /* If the object is hidden or the modifier is not enabled for the viewport is disabled a special
   * handling is required. This is because the viewport dependency graph optimizes out evaluation
   * of objects which are used by hidden objects and disabled modifiers.
   *
   * The idea is to create a dependency graph which does not perform those optimizations. */
  if ((ob_eval->base_flag & BASE_ENABLED_VIEWPORT) == 0 ||
      (md_eval->mode & eModifierMode_Realtime) == 0)
  {
    ViewLayer *view_layer = DEG_get_input_view_layer(depsgraph);

    local_depsgraph = DEG_graph_new(bmain, scene, view_layer, DAG_EVAL_VIEWPORT);
    DEG_disable_visibility_optimization(local_depsgraph);

    DEG_graph_build_from_ids(local_depsgraph, {&ob->id});
    DEG_evaluate_on_refresh(local_depsgraph);

    apply_depsgraph = local_depsgraph;

    /* The evaluated object and modifier are now from the different dependency graph. */
    ob_eval = DEG_get_evaluated(local_depsgraph, ob);
    md_eval = BKE_modifiers_findby_name(ob_eval, md->name);

    /* Force mode on the evaluated modifier, enforcing the modifier evaluation in the apply()
     * functions. */
    md_eval->mode |= eModifierMode_Realtime;
  }

  bool did_apply = false;
  if (mode == MODIFIER_APPLY_SHAPE) {
    did_apply = modifier_apply_shape(bmain, reports, apply_depsgraph, scene, ob, md_eval);
  }
  else {
    did_apply = modifier_apply_obdata(
        reports, apply_depsgraph, scene, ob, md_eval, do_all_keyframes);
  }

  if (did_apply) {
    if (!keep_modifier) {
      BKE_modifier_remove_from_list(ob, md);
      BKE_modifier_free(md);
    }
    BKE_object_free_derived_caches(ob);
  }

  if (local_depsgraph != nullptr) {
    DEG_graph_free(local_depsgraph);
  }

  return true;
}

bool modifier_copy(
    ReportList * /*reports*/, Main *bmain, Scene *scene, Object *ob, ModifierData *md)
{
  if (md->type == eModifierType_ParticleSystem) {
    ModifierData *nmd = object_copy_particle_system(
        bmain, scene, ob, ((ParticleSystemModifierData *)md)->psys);
    BLI_remlink(&ob->modifiers, nmd);
    BLI_insertlinkafter(&ob->modifiers, md, nmd);
    BKE_object_modifier_set_active(ob, nmd);
    return true;
  }

  ModifierData *nmd = BKE_modifier_new(md->type);
  BKE_modifier_copydata(md, nmd);
  BLI_insertlinkafter(&ob->modifiers, md, nmd);
  STRNCPY_UTF8(nmd->name, md->name);
  BKE_modifier_unique_name(&ob->modifiers, nmd);
  BKE_modifiers_persistent_uid_init(*ob, *nmd);
  BKE_object_modifier_set_active(ob, nmd);

  nmd->flag |= eModifierFlag_OverrideLibrary_Local;

  return true;
}

/** \} */

Vector<PointerRNA> modifier_get_edit_objects(const bContext &C, const wmOperator &op)
{
  Vector<PointerRNA> objects;
  if (RNA_boolean_get(op.ptr, "use_selected_objects")) {
    CTX_data_selected_editable_objects(&C, &objects);
  }
  else {
    if (Object *object = context_active_object(&C)) {
      objects.append(RNA_id_pointer_create(&object->id));
    }
  }
  return objects;
}

void modifier_register_use_selected_objects_prop(wmOperatorType *ot)
{
  PropertyRNA *prop = RNA_def_boolean(
      ot->srna,
      "use_selected_objects",
      false,
      "Selected Objects",
      "Affect all selected objects instead of just the active object");
  RNA_def_property_flag(prop, PROP_SKIP_SAVE | PROP_HIDDEN);
}

/* ------------------------------------------------------------------- */
/** \name Add Modifier Operator
 * \{ */

/* Defined with the Grease Pencil Curve setup operator below; used here to auto-build the deform
 * curve the moment the modifier is added through the Add Modifier menu. */
static bool greasepencil_curve_create_and_assign(bContext *C,
                                                 Main *bmain,
                                                 Scene *scene,
                                                 Object *ob,
                                                 GreasePencilCurveModifierData *cmd,
                                                 ReportList *reports);
static bool greasepencil_has_any_point(const Object *ob);

static wmOperatorStatus modifier_add_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  int type = RNA_enum_get(op->ptr, "type");

  bool changed = false;
  for (const PointerRNA &ptr : modifier_get_edit_objects(*C, *op)) {
    Object *ob = static_cast<Object *>(ptr.data);
    ModifierData *new_md = modifier_add(op->reports, bmain, scene, ob, nullptr, type);
    if (new_md == nullptr) {
      continue;
    }
    changed = true;
    /* For the Grease Pencil Curve deform modifier, immediately build a fitted deform curve (left
     * unbound) so the artist can shape it right away instead of needing a separate "Add Deform
     * Curve" click. Skipped while the drawing is still empty (nothing to fit to yet). */
    if (type == eModifierType_GreasePencilCurve && ob->type == OB_GREASE_PENCIL &&
        greasepencil_has_any_point(ob))
    {
      greasepencil_curve_create_and_assign(
          C,
          bmain,
          scene,
          ob,
          reinterpret_cast<GreasePencilCurveModifierData *>(new_md),
          op->reports);
    }
    WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER | NA_ADDED, ob);
  }
  if (!changed) {
    return OPERATOR_CANCELLED;
  }

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_add_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  if (event->modifier & KM_ALT || CTX_wm_view3d(C)) {
    RNA_boolean_set(op->ptr, "use_selected_objects", true);
  }
  if (!RNA_struct_property_is_set(op->ptr, "type")) {
    return WM_menu_invoke(C, op, event);
  }
  return modifier_add_exec(C, op);
}

static const EnumPropertyItem *modifier_add_itemf(bContext *C,
                                                  PointerRNA * /*ptr*/,
                                                  PropertyRNA * /*prop*/,
                                                  bool *r_free)
{
  Object *ob = context_active_object(C);

  if (!ob) {
    return rna_enum_object_modifier_type_items;
  }

  EnumPropertyItem *items = nullptr;
  int totitem = 0;

  const EnumPropertyItem *group_item = nullptr;
  for (int a = 0; rna_enum_object_modifier_type_items[a].identifier; a++) {
    const EnumPropertyItem *md_item = &rna_enum_object_modifier_type_items[a];

    if (md_item->identifier[0]) {
      const ModifierTypeInfo *mti = BKE_modifier_get_info((ModifierType)md_item->value);

      if (mti->flags & eModifierTypeFlag_NoUserAdd) {
        continue;
      }

      if (!BKE_object_support_modifier_type_check(ob, md_item->value)) {
        continue;
      }
    }
    else {
      group_item = md_item;
      continue;
    }

    if (group_item) {
      RNA_enum_item_add(&items, &totitem, group_item);
      group_item = nullptr;
    }

    RNA_enum_item_add(&items, &totitem, md_item);
  }

  RNA_enum_item_end(&items, &totitem);
  *r_free = true;

  return items;
}

void OBJECT_OT_modifier_add(wmOperatorType *ot)
{
  PropertyRNA *prop;

  /* identifiers */
  ot->name = "Add Modifier";
  ot->description = "Add a procedural operation/effect to the active object";
  ot->idname = "OBJECT_OT_modifier_add";

  /* API callbacks. */
  ot->invoke = modifier_add_invoke;
  ot->exec = modifier_add_exec;
  ot->poll = ED_operator_object_active_editable;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  /* properties */
  prop = RNA_def_enum(
      ot->srna, "type", rna_enum_object_modifier_type_items, eModifierType_Subsurf, "Type", "");
  RNA_def_enum_funcs(prop, modifier_add_itemf);
  ot->prop = prop;
  modifier_register_use_selected_objects_prop(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Generic Poll Function and Properties
 *
 * Using modifier names and data context.
 * \{ */

bool edit_modifier_poll_generic(bContext *C,
                                StructRNA *rna_type,
                                int obtype_flag,
                                const bool is_editmode_allowed,
                                const bool is_liboverride_allowed)
{
  Main *bmain = CTX_data_main(C);
  PointerRNA ptr = CTX_data_pointer_get_type(C, "modifier", rna_type);
  Object *ob = (ptr.owner_id) ? (Object *)ptr.owner_id : context_active_object(C);
  ModifierData *mod = static_cast<ModifierData *>(ptr.data); /* May be nullptr. */

  if (mod == nullptr && ob != nullptr) {
    mod = BKE_object_active_modifier(ob);
  }

  if (!ob || !BKE_id_is_editable(bmain, &ob->id)) {
    return false;
  }
  if (obtype_flag && ((1 << ob->type) & obtype_flag) == 0) {
    return false;
  }
  if (ptr.owner_id && !BKE_id_is_editable(bmain, ptr.owner_id)) {
    return false;
  }

  if (!is_liboverride_allowed && BKE_modifier_is_nonlocal_in_liboverride(ob, mod)) {
    CTX_wm_operator_poll_msg_set(
        C, "Cannot edit modifiers coming from linked data in a library override");
    return false;
  }

  if (!is_editmode_allowed && CTX_data_edit_object(C) != nullptr) {
    CTX_wm_operator_poll_msg_set(C, "This modifier operation is not allowed from Edit mode");
    return false;
  }

  return true;
}

static bool edit_modifier_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_Modifier, 0, true, false);
}

/* Used by operators performing actions allowed also on modifiers from the overridden linked object
 * (not only from added 'local' ones). */
static bool edit_modifier_liboverride_allowed_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_Modifier, 0, true, true);
}

void edit_modifier_properties(wmOperatorType *ot)
{
  PropertyRNA *prop = RNA_def_string(
      ot->srna, "modifier", nullptr, MAX_NAME, "Modifier", "Name of the modifier to edit");
  RNA_def_property_flag(prop, PROP_HIDDEN);
}

static void edit_modifier_report_property(wmOperatorType *ot)
{
  PropertyRNA *prop = RNA_def_boolean(
      ot->srna, "report", false, "Report", "Create a notification after the operation");
  RNA_def_property_flag(prop, PROP_HIDDEN);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Generic Invoke Functions
 *
 * Using modifier names and data context.
 * \{ */

bool edit_modifier_invoke_properties(bContext *C, wmOperator *op)
{
  if (RNA_struct_property_is_set(op->ptr, "modifier")) {
    return true;
  }

  PointerRNA ctx_ptr = CTX_data_pointer_get_type(C, "modifier", &RNA_Modifier);
  if (ctx_ptr.data != nullptr) {
    ModifierData *md = static_cast<ModifierData *>(ctx_ptr.data);
    RNA_string_set(op->ptr, "modifier", md->name);
    return true;
  }

  return false;
}

/**
 * If the "modifier" property is not set, fill the modifier property with the name of the modifier
 * with a UI panel below the mouse cursor, unless a specific modifier is set with a context
 * pointer. Used in order to apply modifier operators on hover over their panels.
 */
static bool edit_modifier_invoke_properties_with_hover(bContext *C,
                                                       wmOperator *op,
                                                       const wmEvent *event,
                                                       wmOperatorStatus *r_retval)
{
  if (RNA_struct_find_property(op->ptr, "use_selected_objects")) {
    if (event->modifier & KM_ALT) {
      RNA_boolean_set(op->ptr, "use_selected_objects", true);
    }
  }

  if (RNA_struct_property_is_set(op->ptr, "modifier")) {
    return true;
  }

  /* Note that the context pointer is *not* the active modifier, it is set in UI layouts. */
  PointerRNA ctx_ptr = CTX_data_pointer_get_type(C, "modifier", &RNA_Modifier);
  if (ctx_ptr.data != nullptr) {
    ModifierData *md = static_cast<ModifierData *>(ctx_ptr.data);
    RNA_string_set(op->ptr, "modifier", md->name);
    return true;
  }

  PointerRNA *panel_ptr = UI_region_panel_custom_data_under_cursor(C, event);
  if (panel_ptr == nullptr || RNA_pointer_is_null(panel_ptr)) {
    *r_retval = OPERATOR_CANCELLED;
    return false;
  }

  if (!RNA_struct_is_a(panel_ptr->type, &RNA_Modifier)) {
    /* Work around multiple operators using the same shortcut. The operators for the other
     * stacks in the property editor use the same key, and will not run after these return
     * OPERATOR_CANCELLED. */
    *r_retval = (OPERATOR_PASS_THROUGH | OPERATOR_CANCELLED);
    return false;
  }

  const ModifierData *md = static_cast<const ModifierData *>(panel_ptr->data);
  RNA_string_set(op->ptr, "modifier", md->name);
  return true;
}

ModifierData *edit_modifier_property_get(wmOperator *op, Object *ob, int type)
{
  char modifier_name[MAX_NAME];
  RNA_string_get(op->ptr, "modifier", modifier_name);

  ModifierData *md = BKE_modifiers_findby_name(ob, modifier_name);

  if (md && type != 0 && md->type != type) {
    md = nullptr;
  }

  return md;
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Remove Modifier Operator
 * \{ */

static wmOperatorStatus modifier_remove_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);

  char name[MAX_NAME];
  RNA_string_get(op->ptr, "modifier", name);

  bool changed = false;
  for (const PointerRNA &ptr : modifier_get_edit_objects(*C, *op)) {
    Object *ob = static_cast<Object *>(ptr.data);
    ModifierData *md = BKE_modifiers_findby_name(ob, name);
    if (md == nullptr) {
      continue;
    }

    int mode_orig = ob->mode;
    if (!modifier_remove(op->reports, bmain, scene, ob, md)) {
      continue;
    }

    changed = true;

    WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER | NA_REMOVED, ob);

    /* if cloth/softbody was removed, particle mode could be cleared */
    if (mode_orig & OB_MODE_PARTICLE_EDIT) {
      if ((ob->mode & OB_MODE_PARTICLE_EDIT) == 0) {
        BKE_view_layer_synced_ensure(scene, view_layer);
        if (ob == BKE_view_layer_active_object_get(view_layer)) {
          WM_event_add_notifier(C, NC_SCENE | ND_MODE | NS_MODE_OBJECT, nullptr);
        }
      }
    }
  }

  if (!changed) {
    return OPERATOR_CANCELLED;
  }

  if (RNA_boolean_get(op->ptr, "report")) {
    BKE_reportf(op->reports, RPT_INFO, "Removed modifier: %s", name);
  }

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_remove_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    return modifier_remove_exec(C, op);
  }
  return retval;
}

void OBJECT_OT_modifier_remove(wmOperatorType *ot)
{
  ot->name = "Remove Modifier";
  ot->description = "Remove a modifier from the active object";
  ot->idname = "OBJECT_OT_modifier_remove";

  ot->invoke = modifier_remove_invoke;
  ot->exec = modifier_remove_exec;
  ot->poll = edit_modifier_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
  edit_modifier_report_property(ot);
  modifier_register_use_selected_objects_prop(ot);
}

static wmOperatorStatus modifiers_clear_exec(bContext *C, wmOperator * /*op*/)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);

  CTX_DATA_BEGIN (C, Object *, object, selected_editable_objects) {
    modifiers_clear(bmain, scene, object);
    WM_main_add_notifier(NC_OBJECT | ND_MODIFIER | NA_REMOVED, object);
  }
  CTX_DATA_END;

  return OPERATOR_FINISHED;
}

static bool modifiers_clear_poll(bContext *C)
{
  if (!ED_operator_object_active_local_editable(C)) {
    return false;
  }
  const Object *object = context_active_object(C);
  if (!BKE_object_supports_modifiers(object)) {
    return false;
  }
  return true;
}

void OBJECT_OT_modifiers_clear(wmOperatorType *ot)
{
  ot->name = "Clear Object Modifiers";
  ot->description = "Clear all modifiers from the selected objects";
  ot->idname = "OBJECT_OT_modifiers_clear";

  ot->exec = modifiers_clear_exec;
  ot->poll = modifiers_clear_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Move Up Modifier Operator
 * \{ */

static wmOperatorStatus modifier_move_up_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  ModifierData *md = edit_modifier_property_get(op, ob, 0);

  if (!md || !modifier_move_up(op->reports, RPT_WARNING, ob, md)) {
    return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_move_up_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    return modifier_move_up_exec(C, op);
  }
  return retval;
}

void OBJECT_OT_modifier_move_up(wmOperatorType *ot)
{
  ot->name = "Move Up Modifier";
  ot->description = "Move modifier up in the stack";
  ot->idname = "OBJECT_OT_modifier_move_up";

  ot->invoke = modifier_move_up_invoke;
  ot->exec = modifier_move_up_exec;
  ot->poll = edit_modifier_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Move Down Modifier Operator
 * \{ */

static wmOperatorStatus modifier_move_down_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  ModifierData *md = edit_modifier_property_get(op, ob, 0);

  if (!md || !modifier_move_down(op->reports, RPT_WARNING, ob, md)) {
    return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_move_down_invoke(bContext *C,
                                                  wmOperator *op,
                                                  const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    return modifier_move_down_exec(C, op);
  }
  return retval;
}

void OBJECT_OT_modifier_move_down(wmOperatorType *ot)
{
  ot->name = "Move Down Modifier";
  ot->description = "Move modifier down in the stack";
  ot->idname = "OBJECT_OT_modifier_move_down";

  ot->invoke = modifier_move_down_invoke;
  ot->exec = modifier_move_down_exec;
  ot->poll = edit_modifier_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Move to Index Modifier Operator
 * \{ */

static wmOperatorStatus modifier_move_to_index_exec(bContext *C, wmOperator *op)
{
  char name[MAX_NAME];
  RNA_string_get(op->ptr, "modifier", name);

  const int index = RNA_int_get(op->ptr, "index");

  bool changed = false;
  for (const PointerRNA &ptr : modifier_get_edit_objects(*C, *op)) {
    Object *ob = static_cast<Object *>(ptr.data);
    ModifierData *md = BKE_modifiers_findby_name(ob, name);
    if (!md) {
      continue;
    }

    if (!modifier_move_to_index(op->reports, RPT_WARNING, ob, md, index, true)) {
      continue;
    }
    changed = true;
  }

  if (!changed) {
    return OPERATOR_CANCELLED;
  }

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_move_to_index_invoke(bContext *C,
                                                      wmOperator *op,
                                                      const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    return modifier_move_to_index_exec(C, op);
  }
  return retval;
}

void OBJECT_OT_modifier_move_to_index(wmOperatorType *ot)
{
  ot->name = "Move Active Modifier to Index";
  ot->description =
      "Change the modifier's index in the stack so it evaluates after the set number of others";
  ot->idname = "OBJECT_OT_modifier_move_to_index";

  ot->invoke = modifier_move_to_index_invoke;
  ot->exec = modifier_move_to_index_exec;
  ot->poll = edit_modifier_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
  RNA_def_int(
      ot->srna, "index", 0, 0, INT_MAX, "Index", "The index to move the modifier to", 0, INT_MAX);
  modifier_register_use_selected_objects_prop(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Apply Modifier Operator
 * \{ */

static bool modifier_apply_poll(bContext *C)
{
  if (!edit_modifier_poll_generic(C, &RNA_Modifier, 0, false, false)) {
    return false;
  }

  Scene *scene = CTX_data_scene(C);
  PointerRNA ptr = CTX_data_pointer_get_type(C, "modifier", &RNA_Modifier);
  Object *ob = (ptr.owner_id != nullptr) ? (Object *)ptr.owner_id : context_active_object(C);
  ModifierData *md = static_cast<ModifierData *>(ptr.data); /* May be nullptr. */

  if (ID_IS_OVERRIDE_LIBRARY(ob) || ((ob->data != nullptr) && ID_IS_OVERRIDE_LIBRARY(ob->data))) {
    CTX_wm_operator_poll_msg_set(C, "Modifiers cannot be applied on override data");
    return false;
  }
  if (md != nullptr) {
    if ((ob->mode & OB_MODE_SCULPT) && find_multires_modifier_before(scene, md) &&
        (BKE_modifier_is_same_topology(md) == false))
    {
      CTX_wm_operator_poll_msg_set(
          C, "Constructive modifier cannot be applied to multi-res data in sculpt mode");
      return false;
    }
  }
  return true;
}

static wmOperatorStatus modifier_apply_exec_ex(bContext *C,
                                               wmOperator *op,
                                               int apply_as,
                                               bool keep_modifier)
{
  Main *bmain = CTX_data_main(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  Scene *scene = CTX_data_scene(C);
  Vector<PointerRNA> objects = modifier_get_edit_objects(*C, *op);

  char name[MAX_NAME];
  RNA_string_get(op->ptr, "modifier", name);

  const bool do_report = RNA_boolean_get(op->ptr, "report");
  const int reports_len = do_report ? BLI_listbase_count(&op->reports->list) : 0;

  const bool do_single_user = (apply_as == MODIFIER_APPLY_DATA) ?
                                  RNA_boolean_get(op->ptr, "single_user") :
                                  false;
  const bool do_merge_customdata = (apply_as == MODIFIER_APPLY_DATA) ?
                                       RNA_boolean_get(op->ptr, "merge_customdata") :
                                       false;
  const bool do_all_keyframes = (apply_as == MODIFIER_APPLY_DATA) ?
                                    RNA_boolean_get(op->ptr, "all_keyframes") :
                                    false;

  bool changed = false;
  for (const PointerRNA &ptr : objects) {
    Object *ob = static_cast<Object *>(ptr.data);
    ModifierData *md = BKE_modifiers_findby_name(ob, name);
    if (md == nullptr) {
      continue;
    }

    const ModifierTypeInfo *mti = BKE_modifier_get_info((ModifierType)md->type);

    if (do_single_user && ID_REAL_USERS(ob->data) > 1) {
      single_obdata_user_make(bmain, scene, ob);
      BKE_main_id_newptr_and_tag_clear(bmain);
      WM_event_add_notifier(C, NC_WINDOW, nullptr);
      DEG_relations_tag_update(bmain);
    }

    if (!modifier_apply(bmain,
                        op->reports,
                        depsgraph,
                        scene,
                        ob,
                        md,
                        apply_as,
                        keep_modifier,
                        do_all_keyframes))
    {
      continue;
    }
    changed = true;

    if (ob->type == OB_MESH && do_merge_customdata &&
        ELEM(mti->type, ModifierTypeType::Constructive, ModifierTypeType::Nonconstructive))
    {
      BKE_mesh_merge_customdata_for_apply_modifier((Mesh *)ob->data);
    }

    DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
    DEG_relations_tag_update(bmain);
    WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  }

  if (!changed) {
    return OPERATOR_CANCELLED;
  }

  if (do_report) {
    /* Only add this report if the operator didn't cause another one. The purpose here is
     * to alert that something happened, and the previous report will do that anyway. */
    if (BLI_listbase_count(&op->reports->list) == reports_len) {
      BKE_reportf(op->reports, RPT_INFO, "Applied modifier: %s", name);
    }
  }

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_apply_exec(bContext *C, wmOperator *op)
{
  return modifier_apply_exec_ex(C, op, MODIFIER_APPLY_DATA, false);
}

static wmOperatorStatus modifier_apply_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    PointerRNA ptr = CTX_data_pointer_get_type(C, "modifier", &RNA_Modifier);
    Object *ob = (ptr.owner_id != nullptr) ? (Object *)ptr.owner_id : context_active_object(C);

    if ((ob->data != nullptr) && ID_REAL_USERS(ob->data) > 1) {
      PropertyRNA *prop = RNA_struct_find_property(op->ptr, "single_user");
      if (!RNA_property_is_set(op->ptr, prop)) {
        RNA_property_boolean_set(op->ptr, prop, true);
      }
      if (RNA_property_boolean_get(op->ptr, prop)) {
        return WM_operator_confirm_ex(
            C,
            op,
            IFACE_("Apply Modifier"),
            IFACE_("Make data single-user, apply modifier, and remove it from the list."),
            IFACE_("Apply"),
            ALERT_ICON_WARNING,
            false);
      }
    }
    return modifier_apply_exec(C, op);
  }
  return retval;
}

void OBJECT_OT_modifier_apply(wmOperatorType *ot)
{
  PropertyRNA *prop;

  ot->name = "Apply Modifier";
  ot->description = "Apply modifier and remove from the stack";
  ot->idname = "OBJECT_OT_modifier_apply";

  ot->invoke = modifier_apply_invoke;
  ot->exec = modifier_apply_exec;
  ot->poll = modifier_apply_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;

  edit_modifier_properties(ot);
  edit_modifier_report_property(ot);

  RNA_def_boolean(ot->srna,
                  "merge_customdata",
                  true,
                  "Merge UVs",
                  "For mesh objects, merge UV coordinates that share a vertex to account for "
                  "imprecision in some modifiers");
  prop = RNA_def_boolean(ot->srna,
                         "single_user",
                         false,
                         "Make Data Single User",
                         "Make the object's data single user if needed");
  RNA_def_property_flag(prop, PROP_HIDDEN | PROP_SKIP_SAVE);
  prop = RNA_def_boolean(ot->srna,
                         "all_keyframes",
                         false,
                         "Apply to all keyframes",
                         "For Grease Pencil objects, apply the modifier to all the keyframes");
  RNA_def_property_flag(prop, PROP_HIDDEN | PROP_SKIP_SAVE);
  modifier_register_use_selected_objects_prop(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Apply Modifier As Shape-Key Operator
 * \{ */

static bool modifier_apply_as_shapekey_poll(bContext *C)
{
  return modifier_apply_poll(C);
}

static wmOperatorStatus modifier_apply_as_shapekey_exec(bContext *C, wmOperator *op)
{
  bool keep = RNA_boolean_get(op->ptr, "keep_modifier");

  return modifier_apply_exec_ex(C, op, MODIFIER_APPLY_SHAPE, keep);
}

static wmOperatorStatus modifier_apply_as_shapekey_invoke(bContext *C,
                                                          wmOperator *op,
                                                          const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    return modifier_apply_as_shapekey_exec(C, op);
  }
  return retval;
}

static std::string modifier_apply_as_shapekey_get_description(bContext * /*C*/,
                                                              wmOperatorType * /*ot*/,
                                                              PointerRNA *ptr)
{
  bool keep = RNA_boolean_get(ptr, "keep_modifier");
  if (keep) {
    return TIP_("Apply modifier as a new shapekey and keep it in the stack");
  }

  return "";
}

void OBJECT_OT_modifier_apply_as_shapekey(wmOperatorType *ot)
{
  ot->name = "Apply Modifier as Shape Key";
  ot->description = "Apply modifier as a new shape key and remove from the stack";
  ot->idname = "OBJECT_OT_modifier_apply_as_shapekey";

  ot->invoke = modifier_apply_as_shapekey_invoke;
  ot->exec = modifier_apply_as_shapekey_exec;
  ot->poll = modifier_apply_as_shapekey_poll;
  ot->get_description = modifier_apply_as_shapekey_get_description;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;

  RNA_def_boolean(
      ot->srna, "keep_modifier", false, "Keep Modifier", "Do not remove the modifier from stack");
  edit_modifier_properties(ot);
  edit_modifier_report_property(ot);
  modifier_register_use_selected_objects_prop(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Convert Particle System Modifier to Mesh Operator
 * \{ */

static wmOperatorStatus modifier_convert_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  Object *ob = context_active_object(C);
  ModifierData *md = edit_modifier_property_get(op, ob, 0);

  if (!md || !convert_psys_to_mesh(op->reports, bmain, depsgraph, scene, view_layer, ob, md)) {
    return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_convert_invoke(bContext *C,
                                                wmOperator *op,
                                                const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return modifier_convert_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_modifier_convert(wmOperatorType *ot)
{
  ot->name = "Convert Particles to Mesh";
  ot->description = "Convert particles to a mesh object";
  ot->idname = "OBJECT_OT_modifier_convert";

  ot->invoke = modifier_convert_invoke;
  ot->exec = modifier_convert_exec;
  ot->poll = edit_modifier_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Copy Modifier Operator
 * \{ */

static wmOperatorStatus modifier_copy_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  char name[MAX_NAME];
  RNA_string_get(op->ptr, "modifier", name);

  bool changed = false;
  for (const PointerRNA &ptr : modifier_get_edit_objects(*C, *op)) {
    Object *ob = static_cast<Object *>(ptr.data);
    ModifierData *md = BKE_modifiers_findby_name(ob, name);
    if (!md) {
      continue;
    }

    if (!modifier_copy(op->reports, bmain, scene, ob, md)) {
      continue;
    }
    changed = true;
    DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
    DEG_relations_tag_update(bmain);
    WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER | NA_ADDED, ob);
  }

  if (!changed) {
    return OPERATOR_CANCELLED;
  }

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_copy_invoke(bContext *C, wmOperator *op, const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    return modifier_copy_exec(C, op);
  }
  return retval;
}

void OBJECT_OT_modifier_copy(wmOperatorType *ot)
{
  ot->name = "Copy Modifier";
  ot->description = "Duplicate modifier at the same position in the stack";
  ot->idname = "OBJECT_OT_modifier_copy";

  ot->invoke = modifier_copy_invoke;
  ot->exec = modifier_copy_exec;
  ot->poll = edit_modifier_liboverride_allowed_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
  modifier_register_use_selected_objects_prop(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Set Active Modifier Operator
 * \{ */

static wmOperatorStatus modifier_set_active_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  ModifierData *md = edit_modifier_property_get(op, ob, 0);

  /* If there is no modifier set for this operator, clear the active modifier field. */
  BKE_object_modifier_set_active(ob, md);

  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_set_active_invoke(bContext *C,
                                                   wmOperator *op,
                                                   const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    return modifier_set_active_exec(C, op);
  }
  return retval;
}

void OBJECT_OT_modifier_set_active(wmOperatorType *ot)
{
  ot->name = "Set Active Modifier";
  ot->description = "Activate the modifier to use as the context";
  ot->idname = "OBJECT_OT_modifier_set_active";

  ot->invoke = modifier_set_active_invoke;
  ot->exec = modifier_set_active_exec;
  ot->poll = ED_operator_object_active_only;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Copy Modifier To Selected Operator
 * \{ */

static wmOperatorStatus modifier_copy_to_selected_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  const Scene *scene = CTX_data_scene(C);
  Object *obact = context_active_object(C);
  ModifierData *md = edit_modifier_property_get(op, obact, 0);
  if (!md) {
    return OPERATOR_CANCELLED;
  }

  int num_copied = 0;

  Vector<PointerRNA> selected_objects;
  CTX_data_selected_objects(C, &selected_objects);
  CTX_DATA_BEGIN (C, Object *, ob, selected_objects) {
    if (ob == obact) {
      continue;
    }
    if (!ID_IS_EDITABLE(ob)) {
      continue;
    }
    if (modifier_copy_to_object(bmain, scene, obact, md, ob, op->reports)) {
      WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER | NA_ADDED, ob);
      num_copied++;
    }
  }
  CTX_DATA_END;

  if (num_copied > 0) {
    DEG_relations_tag_update(bmain);
  }
  else {
    BKE_reportf(op->reports, RPT_ERROR, "Modifier '%s' was not copied to any objects", md->name);
    return OPERATOR_CANCELLED;
  }

  return OPERATOR_FINISHED;
}

static wmOperatorStatus modifier_copy_to_selected_invoke(bContext *C,
                                                         wmOperator *op,
                                                         const wmEvent *event)
{
  wmOperatorStatus retval;
  if (edit_modifier_invoke_properties_with_hover(C, op, event, &retval)) {
    return modifier_copy_to_selected_exec(C, op);
  }
  return retval;
}

static bool modifier_copy_to_selected_poll(bContext *C)
{
  PointerRNA ptr = CTX_data_pointer_get_type(C, "modifier", &RNA_Modifier);
  Object *obact = (ptr.owner_id) ? (Object *)ptr.owner_id : context_active_object(C);
  ModifierData *md = static_cast<ModifierData *>(ptr.data);

  /* This just mirrors the check in #BKE_object_copy_modifier,
   * but there is no reasoning for it there. */
  if (md && ELEM(md->type, eModifierType_Hook, eModifierType_Collision)) {
    CTX_wm_operator_poll_msg_set(C, R"(Not supported for "Collision" or "Hook" modifiers)");
    return false;
  }

  if (!obact) {
    CTX_wm_operator_poll_msg_set(C, "No selected object is active");
    return false;
  }

  if (!BKE_object_supports_modifiers(obact)) {
    CTX_wm_operator_poll_msg_set(C, "Object type of source object is not supported");
    return false;
  }

  /* This could have a performance impact in the worst case, where there are many objects selected
   * and none of them pass either of the checks. But that should be uncommon, and this operator is
   * only exposed in a drop-down menu anyway. */
  bool found_supported_objects = false;
  CTX_DATA_BEGIN (C, Object *, ob, selected_objects) {
    if (ob == obact) {
      continue;
    }

    if (!md) {
      /* Skip type check if modifier could not be found ("modifier" context variable not set). */
      if (BKE_object_supports_modifiers(ob)) {
        found_supported_objects = true;
        break;
      }
    }
    else if (BKE_object_support_modifier_type_check(ob, md->type)) {
      found_supported_objects = true;
      break;
    }
  }
  CTX_DATA_END;

  if (!found_supported_objects) {
    CTX_wm_operator_poll_msg_set(C, "No supported objects were selected");
    return false;
  }
  return true;
}

void OBJECT_OT_modifier_copy_to_selected(wmOperatorType *ot)
{
  ot->name = "Copy Modifier to Selected";
  ot->description = "Copy the modifier from the active object to all selected objects";
  ot->idname = "OBJECT_OT_modifier_copy_to_selected";

  ot->invoke = modifier_copy_to_selected_invoke;
  ot->exec = modifier_copy_to_selected_exec;
  ot->poll = modifier_copy_to_selected_poll;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

static wmOperatorStatus object_modifiers_copy_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  const Scene *scene = CTX_data_scene(C);
  Object *active_object = context_active_object(C);

  Vector<PointerRNA> selected_objects;
  CTX_data_selected_objects(C, &selected_objects);
  CTX_DATA_BEGIN (C, Object *, object, selected_objects) {
    if (object == active_object) {
      continue;
    }
    LISTBASE_FOREACH (const ModifierData *, md, &active_object->modifiers) {
      if (modifier_copy_to_object(bmain, scene, active_object, md, object, op->reports)) {
        WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER | NA_ADDED, object);
      }
    }
  }
  CTX_DATA_END;

  return OPERATOR_FINISHED;

  DEG_relations_tag_update(bmain);

  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER | NA_ADDED, nullptr);

  return OPERATOR_FINISHED;
}

static bool modifiers_copy_to_selected_poll(bContext *C)
{
  if (!ED_operator_object_active_editable(C)) {
    return false;
  }
  const Object *active_object = context_active_object(C);
  if (!BKE_object_supports_modifiers(active_object)) {
    return false;
  }
  if (BLI_listbase_is_empty(&active_object->modifiers)) {
    CTX_wm_operator_poll_msg_set(C, "Active object has no modifiers");
    return false;
  }
  return true;
}

void OBJECT_OT_modifiers_copy_to_selected(wmOperatorType *ot)
{
  ot->name = "Copy Modifiers to Selected Objects";
  ot->idname = "OBJECT_OT_modifiers_copy_to_selected";
  ot->description = "Copy modifiers to other selected objects";

  ot->exec = object_modifiers_copy_exec;
  ot->poll = modifiers_copy_to_selected_poll;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Skin Modifier
 * \{ */

static void modifier_skin_customdata_delete(Object *ob)
{
  Mesh *mesh = static_cast<Mesh *>(ob->data);
  if (BMEditMesh *em = mesh->runtime->edit_mesh.get()) {
    BM_data_layer_free(em->bm, &em->bm->vdata, CD_MVERT_SKIN);
  }
  else {
    CustomData_free_layer_active(&mesh->vert_data, CD_MVERT_SKIN);
  }
}

static bool skin_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_SkinModifier, (1 << OB_MESH), false, false);
}

static bool skin_edit_poll(bContext *C)
{
  Object *ob = CTX_data_edit_object(C);
  return (ob != nullptr &&
          edit_modifier_poll_generic(C, &RNA_SkinModifier, (1 << OB_MESH), true, false) &&
          !ID_IS_OVERRIDE_LIBRARY(ob) && !ID_IS_OVERRIDE_LIBRARY(ob->data));
}

static void skin_root_clear(BMVert *bm_vert, GSet *visited, const int cd_vert_skin_offset)
{
  BMEdge *bm_edge;
  BMIter bm_iter;

  BM_ITER_ELEM (bm_edge, &bm_iter, bm_vert, BM_EDGES_OF_VERT) {
    BMVert *v2 = BM_edge_other_vert(bm_edge, bm_vert);

    if (BLI_gset_add(visited, v2)) {
      MVertSkin *vs = static_cast<MVertSkin *>(BM_ELEM_CD_GET_VOID_P(v2, cd_vert_skin_offset));

      /* clear vertex root flag and add to visited set */
      vs->flag &= ~MVERT_SKIN_ROOT;

      skin_root_clear(v2, visited, cd_vert_skin_offset);
    }
  }
}

static wmOperatorStatus skin_root_mark_exec(bContext *C, wmOperator * /*op*/)
{
  Object *ob = CTX_data_edit_object(C);
  BMEditMesh *em = BKE_editmesh_from_object(ob);
  BMesh *bm = em->bm;

  GSet *visited = BLI_gset_ptr_new(__func__);

  BKE_mesh_ensure_skin_customdata(static_cast<Mesh *>(ob->data));

  const int cd_vert_skin_offset = CustomData_get_offset(&bm->vdata, CD_MVERT_SKIN);

  BMVert *bm_vert;
  BMIter bm_iter;
  BM_ITER_MESH (bm_vert, &bm_iter, bm, BM_VERTS_OF_MESH) {
    if (BM_elem_flag_test(bm_vert, BM_ELEM_SELECT) && BLI_gset_add(visited, bm_vert)) {
      MVertSkin *vs = static_cast<MVertSkin *>(
          BM_ELEM_CD_GET_VOID_P(bm_vert, cd_vert_skin_offset));

      /* mark vertex as root and add to visited set */
      vs->flag |= MVERT_SKIN_ROOT;

      /* clear root flag from all connected vertices (recursively) */
      skin_root_clear(bm_vert, visited, cd_vert_skin_offset);
    }
  }

  BLI_gset_free(visited, nullptr);

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

void OBJECT_OT_skin_root_mark(wmOperatorType *ot)
{
  ot->name = "Skin Root Mark";
  ot->description = "Mark selected vertices as roots";
  ot->idname = "OBJECT_OT_skin_root_mark";

  ot->poll = skin_edit_poll;
  ot->exec = skin_root_mark_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

enum SkinLooseAction {
  SKIN_LOOSE_MARK,
  SKIN_LOOSE_CLEAR,
};

static wmOperatorStatus skin_loose_mark_clear_exec(bContext *C, wmOperator *op)
{
  Object *ob = CTX_data_edit_object(C);
  BMEditMesh *em = BKE_editmesh_from_object(ob);
  BMesh *bm = em->bm;
  SkinLooseAction action = static_cast<SkinLooseAction>(RNA_enum_get(op->ptr, "action"));

  if (!CustomData_has_layer(&bm->vdata, CD_MVERT_SKIN)) {
    return OPERATOR_CANCELLED;
  }

  BMVert *bm_vert;
  BMIter bm_iter;
  BM_ITER_MESH (bm_vert, &bm_iter, bm, BM_VERTS_OF_MESH) {
    if (BM_elem_flag_test(bm_vert, BM_ELEM_SELECT)) {
      MVertSkin *vs = static_cast<MVertSkin *>(
          CustomData_bmesh_get(&bm->vdata, bm_vert->head.data, CD_MVERT_SKIN));

      switch (action) {
        case SKIN_LOOSE_MARK:
          vs->flag |= MVERT_SKIN_LOOSE;
          break;
        case SKIN_LOOSE_CLEAR:
          vs->flag &= ~MVERT_SKIN_LOOSE;
          break;
      }
    }
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

void OBJECT_OT_skin_loose_mark_clear(wmOperatorType *ot)
{
  static const EnumPropertyItem action_items[] = {
      {SKIN_LOOSE_MARK, "MARK", 0, "Mark", "Mark selected vertices as loose"},
      {SKIN_LOOSE_CLEAR, "CLEAR", 0, "Clear", "Set selected vertices as not loose"},
      {0, nullptr, 0, nullptr, nullptr},
  };

  ot->name = "Skin Mark/Clear Loose";
  ot->description = "Mark/clear selected vertices as loose";
  ot->idname = "OBJECT_OT_skin_loose_mark_clear";

  ot->poll = skin_edit_poll;
  ot->exec = skin_loose_mark_clear_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_enum(ot->srna, "action", action_items, SKIN_LOOSE_MARK, "Action", nullptr);
}

static wmOperatorStatus skin_radii_equalize_exec(bContext *C, wmOperator * /*op*/)
{
  Object *ob = CTX_data_edit_object(C);
  BMEditMesh *em = BKE_editmesh_from_object(ob);
  BMesh *bm = em->bm;

  if (!CustomData_has_layer(&bm->vdata, CD_MVERT_SKIN)) {
    return OPERATOR_CANCELLED;
  }

  BMVert *bm_vert;
  BMIter bm_iter;
  BM_ITER_MESH (bm_vert, &bm_iter, bm, BM_VERTS_OF_MESH) {
    if (BM_elem_flag_test(bm_vert, BM_ELEM_SELECT)) {
      MVertSkin *vs = static_cast<MVertSkin *>(
          CustomData_bmesh_get(&bm->vdata, bm_vert->head.data, CD_MVERT_SKIN));
      float avg = (vs->radius[0] + vs->radius[1]) * 0.5f;

      vs->radius[0] = vs->radius[1] = avg;
    }
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

void OBJECT_OT_skin_radii_equalize(wmOperatorType *ot)
{
  ot->name = "Skin Radii Equalize";
  ot->description = "Make skin radii of selected vertices equal on each axis";
  ot->idname = "OBJECT_OT_skin_radii_equalize";

  ot->poll = skin_edit_poll;
  ot->exec = skin_radii_equalize_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

static void skin_armature_bone_create(Object *skin_ob,
                                      const Span<float3> positions,
                                      const int2 *edges,
                                      bArmature *arm,
                                      BLI_bitmap *edges_visited,
                                      const GroupedSpan<int> emap,
                                      EditBone *parent_bone,
                                      int parent_v)
{
  for (int i = 0; i < emap[parent_v].size(); i++) {
    int endx = emap[parent_v][i];
    const int2 &edge = edges[endx];

    /* ignore edge if already visited */
    if (BLI_BITMAP_TEST(edges_visited, endx)) {
      continue;
    }
    BLI_BITMAP_ENABLE(edges_visited, endx);

    int v = bke::mesh::edge_other_vert(edge, parent_v);

    EditBone *bone = ED_armature_ebone_add(arm, "Bone");

    bone->parent = parent_bone;
    if (parent_bone != nullptr) {
      bone->flag |= BONE_CONNECTED;
    }

    copy_v3_v3(bone->head, positions[parent_v]);
    copy_v3_v3(bone->tail, positions[v]);
    bone->rad_head = bone->rad_tail = 0.25;
    SNPRINTF_UTF8(bone->name, "Bone.%.2d", endx);

    /* add bDeformGroup */
    bDeformGroup *dg = BKE_object_defgroup_add_name(skin_ob, bone->name);
    if (dg != nullptr) {
      blender::ed::object::vgroup_vert_add(skin_ob, dg, parent_v, 1, WEIGHT_REPLACE);
      blender::ed::object::vgroup_vert_add(skin_ob, dg, v, 1, WEIGHT_REPLACE);
    }

    skin_armature_bone_create(skin_ob, positions, edges, arm, edges_visited, emap, bone, v);
  }
}

static Object *modifier_skin_armature_create(Depsgraph *depsgraph, Main *bmain, Object *skin_ob)
{
  Mesh *mesh = static_cast<Mesh *>(skin_ob->data);
  const Span<float3> me_positions = mesh->vert_positions();
  const Span<int2> me_edges = mesh->edges();

  Scene *scene_eval = DEG_get_evaluated_scene(depsgraph);
  Object *ob_eval = DEG_get_evaluated(depsgraph, skin_ob);

  const Mesh *me_eval_deform = blender::bke::mesh_get_eval_deform(
      depsgraph, scene_eval, ob_eval, &CD_MASK_BAREMESH);
  const Span<float3> positions_eval = me_eval_deform->vert_positions();

  /* add vertex weights to original mesh */
  mesh->deform_verts_for_write();

  Scene *scene = DEG_get_input_scene(depsgraph);
  ViewLayer *view_layer = DEG_get_input_view_layer(depsgraph);
  Object *arm_ob = BKE_object_add(bmain, scene, view_layer, OB_ARMATURE, nullptr);
  BKE_object_transform_copy(arm_ob, skin_ob);
  bArmature *arm = static_cast<bArmature *>(arm_ob->data);
  ANIM_armature_bonecoll_show_all(arm);
  arm_ob->dtx |= OB_DRAW_IN_FRONT;
  arm->drawtype = ARM_DRAW_TYPE_STICK;
  arm->edbo = MEM_callocN<ListBase>("edbo armature");

  MVertSkin *mvert_skin = static_cast<MVertSkin *>(
      CustomData_get_layer_for_write(&mesh->vert_data, CD_MVERT_SKIN, mesh->verts_num));

  Array<int> vert_to_edge_offsets;
  Array<int> vert_to_edge_indices;
  const GroupedSpan<int> emap = bke::mesh::build_vert_to_edge_map(
      me_edges, mesh->verts_num, vert_to_edge_offsets, vert_to_edge_indices);

  BLI_bitmap *edges_visited = BLI_BITMAP_NEW(mesh->edges_num, "edge_visited");

  /* NOTE: we use EditBones here, easier to set them up and use
   * edit-armature functions to convert back to regular bones */
  for (int v = 0; v < mesh->verts_num; v++) {
    if (mvert_skin[v].flag & MVERT_SKIN_ROOT) {
      EditBone *bone = nullptr;

      /* Unless the skin root has just one adjacent edge, create
       * a fake root bone (have it going off in the Y direction
       * (arbitrary) */
      if (emap[v].size() > 1) {
        bone = ED_armature_ebone_add(arm, "Bone");

        copy_v3_v3(bone->head, me_positions[v]);
        copy_v3_v3(bone->tail, me_positions[v]);

        bone->head[1] = 1.0f;
        bone->rad_head = bone->rad_tail = 0.25;
      }

      if (emap[v].size() >= 1) {
        skin_armature_bone_create(
            skin_ob, positions_eval, me_edges.data(), arm, edges_visited, emap, bone, v);
      }
    }
  }

  MEM_freeN(edges_visited);

  ED_armature_from_edit(bmain, arm);
  ED_armature_edit_free(arm);

  return arm_ob;
}

static wmOperatorStatus skin_armature_create_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  Object *ob = CTX_data_active_object(C);
  Mesh *mesh = static_cast<Mesh *>(ob->data);
  ModifierData *skin_md;

  if (!CustomData_has_layer(&mesh->vert_data, CD_MVERT_SKIN)) {
    BKE_reportf(op->reports, RPT_WARNING, "Mesh '%s' has no skin vertex data", mesh->id.name + 2);
    return OPERATOR_CANCELLED;
  }

  /* create new armature */
  Object *arm_ob = modifier_skin_armature_create(depsgraph, bmain, ob);

  /* add a modifier to connect the new armature to the mesh */
  ArmatureModifierData *arm_md = (ArmatureModifierData *)BKE_modifier_new(eModifierType_Armature);
  if (arm_md) {
    skin_md = edit_modifier_property_get(op, ob, eModifierType_Skin);
    BLI_insertlinkafter(&ob->modifiers, skin_md, arm_md);
    BKE_modifiers_persistent_uid_init(*arm_ob, arm_md->modifier);

    arm_md->object = arm_ob;
    arm_md->deformflag = ARM_DEF_VGROUP | ARM_DEF_QUATERNION;
    DEG_relations_tag_update(bmain);
    DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  }

  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus skin_armature_create_invoke(bContext *C,
                                                    wmOperator *op,
                                                    const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return skin_armature_create_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_skin_armature_create(wmOperatorType *ot)
{
  ot->name = "Skin Armature Create";
  ot->description = "Create an armature that parallels the skin layout";
  ot->idname = "OBJECT_OT_skin_armature_create";

  ot->poll = skin_poll;
  ot->invoke = skin_armature_create_invoke;
  ot->exec = skin_armature_create_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Delta Mesh Bind Operator
 * \{ */

static bool correctivesmooth_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_CorrectiveSmoothModifier, 0, true, false);
}

static wmOperatorStatus correctivesmooth_bind_exec(bContext *C, wmOperator *op)
{
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  Scene *scene = CTX_data_scene(C);
  Object *ob = context_active_object(C);
  CorrectiveSmoothModifierData *csmd = (CorrectiveSmoothModifierData *)edit_modifier_property_get(
      op, ob, eModifierType_CorrectiveSmooth);

  if (!csmd) {
    return OPERATOR_CANCELLED;
  }

  if (!BKE_modifier_is_enabled(scene, &csmd->modifier, eModifierMode_Realtime)) {
    BKE_report(op->reports, RPT_ERROR, "Modifier is disabled");
    return OPERATOR_CANCELLED;
  }

  const bool is_bind = (csmd->bind_coords != nullptr);

  implicit_sharing::free_shared_data(&csmd->bind_coords, &csmd->bind_coords_sharing_info);
  MEM_SAFE_FREE(csmd->delta_cache.deltas);

  if (is_bind) {
    /* toggle off */
    csmd->bind_coords_num = 0;
  }
  else {
    /* Signal to modifier to recalculate. */
    CorrectiveSmoothModifierData *csmd_eval = (CorrectiveSmoothModifierData *)
        BKE_modifier_get_evaluated(depsgraph, ob, &csmd->modifier);
    csmd_eval->bind_coords_num = uint(-1);

    /* Force modifier to run, it will call binding routine
     * (this has to happen outside of depsgraph evaluation). */
    object_force_modifier_bind_simple_options(depsgraph, ob, &csmd->modifier);
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus correctivesmooth_bind_invoke(bContext *C,
                                                     wmOperator *op,
                                                     const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return correctivesmooth_bind_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_correctivesmooth_bind(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Corrective Smooth Bind";
  ot->description = "Bind base pose in Corrective Smooth modifier";
  ot->idname = "OBJECT_OT_correctivesmooth_bind";

  /* API callbacks. */
  ot->poll = correctivesmooth_poll;
  ot->invoke = correctivesmooth_bind_invoke;
  ot->exec = correctivesmooth_bind_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Mesh Deform Bind Operator
 * \{ */

static bool meshdeform_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_MeshDeformModifier, 0, true, false);
}

static wmOperatorStatus meshdeform_bind_exec(bContext *C, wmOperator *op)
{
  using namespace blender;
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  Object *ob = context_active_object(C);
  MeshDeformModifierData *mmd = (MeshDeformModifierData *)edit_modifier_property_get(
      op, ob, eModifierType_MeshDeform);

  if (mmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  if (mmd->bindcagecos != nullptr) {
    implicit_sharing::free_shared_data(&mmd->bindcagecos, &mmd->bindcagecos_sharing_info);
    implicit_sharing::free_shared_data(&mmd->dyngrid, &mmd->dyngrid_sharing_info);
    implicit_sharing::free_shared_data(&mmd->dyninfluences, &mmd->dyninfluences_sharing_info);
    implicit_sharing::free_shared_data(&mmd->bindinfluences, &mmd->bindinfluences_sharing_info);
    implicit_sharing::free_shared_data(&mmd->bindoffsets, &mmd->bindoffsets_sharing_info);
    implicit_sharing::free_shared_data(&mmd->dynverts, &mmd->dynverts_sharing_info);
    MEM_SAFE_FREE(mmd->bindweights); /* Deprecated */
    MEM_SAFE_FREE(mmd->bindcos);     /* Deprecated */
    mmd->verts_num = 0;
    mmd->cage_verts_num = 0;
    mmd->influences_num = 0;
  }
  else {
    /* Force modifier to run, it will call binding routine
     * (this has to happen outside of depsgraph evaluation). */
    MeshDeformModifierData *mmd_eval = (MeshDeformModifierData *)BKE_modifier_get_evaluated(
        depsgraph, ob, &mmd->modifier);
    mmd_eval->bindfunc = ED_mesh_deform_bind_callback;
    object_force_modifier_bind_simple_options(depsgraph, ob, &mmd->modifier);
    mmd_eval->bindfunc = nullptr;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus meshdeform_bind_invoke(bContext *C,
                                               wmOperator *op,
                                               const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return meshdeform_bind_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_meshdeform_bind(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Mesh Deform Bind";
  ot->description = "Bind mesh to cage in mesh deform modifier";
  ot->idname = "OBJECT_OT_meshdeform_bind";

  /* API callbacks. */
  ot->poll = meshdeform_poll;
  ot->invoke = meshdeform_bind_invoke;
  ot->exec = meshdeform_bind_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Explode Refresh Operator
 * \{ */

static bool explode_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_ExplodeModifier, 0, true, false);
}

static wmOperatorStatus explode_refresh_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  ExplodeModifierData *emd = (ExplodeModifierData *)edit_modifier_property_get(
      op, ob, eModifierType_Explode);

  if (!emd) {
    return OPERATOR_CANCELLED;
  }

  emd->flag |= eExplodeFlag_CalcFaces;

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus explode_refresh_invoke(bContext *C,
                                               wmOperator *op,
                                               const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return explode_refresh_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_explode_refresh(wmOperatorType *ot)
{
  ot->name = "Explode Refresh";
  ot->description = "Refresh data in the Explode modifier";
  ot->idname = "OBJECT_OT_explode_refresh";

  ot->poll = explode_poll;
  ot->invoke = explode_refresh_invoke;
  ot->exec = explode_refresh_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Ocean Bake Operator
 * \{ */

static bool ocean_bake_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_OceanModifier, 0, true, false);
}

struct OceanBakeJob {
  /* from wmJob */
  Object *owner;
  bool *stop, *do_update;
  float *progress;
  int current_frame;
  OceanCache *och;
  Ocean *ocean;
  OceanModifierData *omd;
};

static void oceanbake_free(void *customdata)
{
  OceanBakeJob *oj = static_cast<OceanBakeJob *>(customdata);
  MEM_delete(oj);
}

/* called by oceanbake, only to check job 'stop' value */
static int oceanbake_breakjob(void * /*customdata*/)
{
  // OceanBakeJob *ob = (OceanBakeJob *)customdata;
  // return *(ob->stop);

  /* this is not nice yet, need to make the jobs list template better
   * for identifying/acting upon various different jobs */
  /* but for now we'll reuse the render break... */
  return (G.is_break);
}

/* called by oceanbake, wmJob sends notifier */
static void oceanbake_update(void *customdata, float progress, int *cancel)
{
  OceanBakeJob *oj = static_cast<OceanBakeJob *>(customdata);

  if (oceanbake_breakjob(oj)) {
    *cancel = 1;
  }

  *(oj->do_update) = true;
  *(oj->progress) = progress;
}

static void oceanbake_startjob(void *customdata, wmJobWorkerStatus *worker_status)
{
  OceanBakeJob *oj = static_cast<OceanBakeJob *>(customdata);

  oj->stop = &worker_status->stop;
  oj->do_update = &worker_status->do_update;
  oj->progress = &worker_status->progress;

  G.is_break = false; /* XXX shared with render - replace with job 'stop' switch */

  BKE_ocean_bake(oj->ocean, oj->och, oceanbake_update, (void *)oj);

  worker_status->do_update = true;
  worker_status->stop = false;
}

static void oceanbake_endjob(void *customdata)
{
  OceanBakeJob *oj = static_cast<OceanBakeJob *>(customdata);

  if (oj->ocean) {
    BKE_ocean_free(oj->ocean);
    oj->ocean = nullptr;
  }

  oj->omd->oceancache = oj->och;
  oj->omd->cached = true;

  Object *ob = oj->owner;
  DEG_id_tag_update(&ob->id, ID_RECALC_SYNC_TO_EVAL);
}

static wmOperatorStatus ocean_bake_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Object *ob = context_active_object(C);
  OceanModifierData *omd = (OceanModifierData *)edit_modifier_property_get(
      op, ob, eModifierType_Ocean);
  Scene *scene = CTX_data_scene(C);
  const bool free = RNA_boolean_get(op->ptr, "free");

  if (!omd) {
    return OPERATOR_CANCELLED;
  }

  if (free) {
    BKE_ocean_free_modifier_cache(omd);
    DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
    WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
    return OPERATOR_FINISHED;
  }

  OceanCache *och = BKE_ocean_init_cache(omd->cachepath,
                                         BKE_modifier_path_relbase(bmain, ob),
                                         omd->bakestart,
                                         omd->bakeend,
                                         omd->wave_scale,
                                         omd->chop_amount,
                                         omd->foam_coverage,
                                         omd->foam_fade,
                                         omd->resolution);

  och->time = MEM_malloc_arrayN<float>(och->duration, "foam bake time");

  int cfra = scene->r.cfra;

  /* precalculate time variable before baking */
  int i = 0;
  Depsgraph *depsgraph = CTX_data_depsgraph_pointer(C);
  for (int f = omd->bakestart; f <= omd->bakeend; f++) {
    /* For now only simple animation of time value is supported, nothing else.
     * No drivers or other modifier parameters. */
    /* TODO(sergey): This operates on an original data, so no flush is needed. However, baking
     * usually should happen on an evaluated objects, so this seems to be deeper issue here. */

    const AnimationEvalContext anim_eval_context = BKE_animsys_eval_context_construct(depsgraph,
                                                                                      f);
    BKE_animsys_evaluate_animdata((ID *)ob, ob->adt, &anim_eval_context, ADT_RECALC_ANIM, false);

    och->time[i] = omd->time;
    i++;
  }

  /* Make a copy of ocean to use for baking - thread-safety. */
  Ocean *ocean = BKE_ocean_add();
  BKE_ocean_init_from_modifier(ocean, omd, omd->resolution);

#if 0
  BKE_ocean_bake(ocean, och);

  omd->oceancache = och;
  omd->cached = true;

  scene->r.cfra = cfra;

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
#endif

  /* job stuff */

  scene->r.cfra = cfra;

  /* setup job */
  wmJob *wm_job = WM_jobs_get(CTX_wm_manager(C),
                              CTX_wm_window(C),
                              scene,
                              "Simulating ocean...",
                              WM_JOB_PROGRESS,
                              WM_JOB_TYPE_OBJECT_SIM_OCEAN);
  OceanBakeJob *oj = MEM_callocN<OceanBakeJob>("ocean bake job");
  oj->owner = ob;
  oj->ocean = ocean;
  oj->och = och;
  oj->omd = omd;

  WM_jobs_customdata_set(wm_job, oj, oceanbake_free);
  WM_jobs_timer(wm_job, 0.1, NC_OBJECT | ND_MODIFIER, NC_OBJECT | ND_MODIFIER);
  WM_jobs_callbacks(wm_job, oceanbake_startjob, nullptr, nullptr, oceanbake_endjob);

  WM_jobs_start(CTX_wm_manager(C), wm_job);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus ocean_bake_invoke(bContext *C, wmOperator *op, const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return ocean_bake_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_ocean_bake(wmOperatorType *ot)
{
  ot->name = "Bake Ocean";
  ot->description = "Bake an image sequence of ocean data";
  ot->idname = "OBJECT_OT_ocean_bake";

  ot->poll = ocean_bake_poll;
  ot->invoke = ocean_bake_invoke;
  ot->exec = ocean_bake_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);

  RNA_def_boolean(ot->srna, "free", false, "Free", "Free the bake, rather than generating it");
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Laplacian-Deform Bind Operator
 * \{ */

static bool laplaciandeform_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_LaplacianDeformModifier, 0, false, false);
}

static wmOperatorStatus laplaciandeform_bind_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  LaplacianDeformModifierData *lmd = (LaplacianDeformModifierData *)edit_modifier_property_get(
      op, ob, eModifierType_LaplacianDeform);

  if (lmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  if (lmd->flag & MOD_LAPLACIANDEFORM_BIND) {
    lmd->flag &= ~MOD_LAPLACIANDEFORM_BIND;
  }
  else {
    lmd->flag |= MOD_LAPLACIANDEFORM_BIND;
  }

  LaplacianDeformModifierData *lmd_eval = (LaplacianDeformModifierData *)
      BKE_modifier_get_evaluated(depsgraph, ob, &lmd->modifier);
  lmd_eval->flag = lmd->flag;

  /* Force modifier to run, it will call binding routine
   * (this has to happen outside of depsgraph evaluation). */
  object_force_modifier_bind_simple_options(depsgraph, ob, &lmd->modifier);

  /* This is hard to know from the modifier itself whether the evaluation is
   * happening for binding or not. So we copy all the required data here. */
  lmd->verts_num = lmd_eval->verts_num;
  if (lmd_eval->vertexco == nullptr) {
    implicit_sharing::free_shared_data(&lmd->vertexco, &lmd->vertexco_sharing_info);
  }
  else {
    implicit_sharing::copy_shared_pointer(lmd_eval->vertexco,
                                          lmd_eval->vertexco_sharing_info,
                                          &lmd->vertexco,
                                          &lmd->vertexco_sharing_info);
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus laplaciandeform_bind_invoke(bContext *C,
                                                    wmOperator *op,
                                                    const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return laplaciandeform_bind_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_laplaciandeform_bind(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Laplacian Deform Bind";
  ot->description = "Bind mesh to system in laplacian deform modifier";
  ot->idname = "OBJECT_OT_laplaciandeform_bind";

  /* API callbacks. */
  ot->poll = laplaciandeform_poll;
  ot->invoke = laplaciandeform_bind_invoke;
  ot->exec = laplaciandeform_bind_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Surface Deform Bind Operator
 * \{ */

static bool surfacedeform_bind_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_SurfaceDeformModifier, 0, true, false);
}

static wmOperatorStatus surfacedeform_bind_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  SurfaceDeformModifierData *smd = (SurfaceDeformModifierData *)edit_modifier_property_get(
      op, ob, eModifierType_SurfaceDeform);

  if (smd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  if (smd->flags & MOD_SDEF_BIND) {
    smd->flags &= ~MOD_SDEF_BIND;
  }
  else if (smd->target) {
    smd->flags |= MOD_SDEF_BIND;
  }

  SurfaceDeformModifierData *smd_eval = (SurfaceDeformModifierData *)BKE_modifier_get_evaluated(
      depsgraph, ob, &smd->modifier);
  smd_eval->flags = smd->flags;

  /* Force modifier to run, it will call binding routine
   * (this has to happen outside of depsgraph evaluation). */
  object_force_modifier_bind_simple_options(depsgraph, ob, &smd->modifier);

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus surfacedeform_bind_invoke(bContext *C,
                                                  wmOperator *op,
                                                  const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return surfacedeform_bind_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_surfacedeform_bind(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Surface Deform Bind";
  ot->description = "Bind mesh to target in surface deform modifier";
  ot->idname = "OBJECT_OT_surfacedeform_bind";

  /* API callbacks. */
  ot->poll = surfacedeform_bind_poll;
  ot->invoke = surfacedeform_bind_invoke;
  ot->exec = surfacedeform_bind_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Grease Pencil Curve Deform Bind Operator
 * \{ */

static bool greasepencil_curve_bind_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_GreasePencilCurveModifier, 0, true, false);
}

/* Core of the bind: store (or clear, when `unbind`) the per-point rest-pose binding of `ob`'s
 * drawings against `curve_ob`. Shared by the manual Bind button and the one-click setup operator
 * below. Returns false (and reports) on failure. */
/* Defined below (just before the curve-create helper); used here to refresh the rest snapshot. */
static void curve_store_rest(Object *curve_ob);

/* True when `ob` tracks a peg rig through a Follow Peg constraint, i.e. it already has a source of
 * motion of its own and must not be parented on top of it. */
static bool object_follows_peg(const Object *ob)
{
  if (ob == nullptr) {
    return false;
  }
  LISTBASE_FOREACH (const bConstraint *, con, &ob->constraints) {
    if (con->type == CONSTRAINT_TYPE_FOLLOWPEG) {
      return true;
    }
  }
  return false;
}

static bool greasepencil_curve_bind_drawings(Depsgraph *depsgraph,
                                             Object *ob,
                                             GreasePencilCurveModifierData *cmd,
                                             const bool unbind,
                                             ReportList *reports)
{
  GreasePencil &grease_pencil = *static_cast<GreasePencil *>(ob->data);
  Object *curve_ob = cmd->object;

  if (unbind) {
    for (GreasePencilDrawingBase *base : grease_pencil.drawings()) {
      if (base->type != GP_DRAWING) {
        continue;
      }
      bke::greasepencil::Drawing &drawing = reinterpret_cast<GreasePencilDrawing *>(base)->wrap();
      bke::MutableAttributeAccessor attributes =
          drawing.strokes_for_write().attributes_for_write();
      attributes.remove(greasepencil_curve::ATTR_U);
      attributes.remove(greasepencil_curve::ATTR_OFFSET);
      attributes.remove(greasepencil_curve::ATTR_BOUND);
    }
    MEM_SAFE_FREE(cmd->rest_samples);
    cmd->rest_samples_num = 0;
    return true;
  }

  if (curve_ob == nullptr || curve_ob->type != OB_CURVES_LEGACY) {
    BKE_report(reports, RPT_ERROR, "Assign a curve object before binding");
    return false;
  }
  const Object *curve_eval = DEG_get_evaluated(depsgraph, curve_ob);

  /* Drawing-plane normal expressed in the curve's local space (the GP local Y axis is the flat
   * drawing's normal). Used to build a planar, twist-free frame along the curve. */
  const float4x4 gp_to_curve = curve_eval->world_to_object() * ob->object_to_world();
  const float3 plane_normal = math::normalize(float3x3(gp_to_curve) * float3(0.0f, 1.0f, 0.0f));

  /* Sample the rest curve evenly by arc length once, in curve-local space. `sample_*` is packed
   * (failed samples skipped) for the nearest-point search below, while `rest` keeps the full
   * 256-entry table indexed by k, because that is how the modifier addresses it (it rounds the
   * stored u back to k). */
  const int sample_count = 256;
  const int stride = MOD_GREASE_PENCIL_CURVE_REST_STRIDE;
  Array<float3> sample_pos(sample_count);
  Array<float3x3> sample_frame(sample_count);
  Array<float> sample_u(sample_count);
  float *rest = MEM_calloc_arrayN<float>(size_t(sample_count) * stride, __func__);
  int valid = 0;
  for (int k = 0; k < sample_count; k++) {
    const float u = float(k) / float(sample_count - 1);
    float3 pos;
    float3x3 frame;
    if (greasepencil_curve::sample_curve(*curve_eval, u, plane_normal, pos, frame)) {
      sample_u[valid] = u;
      sample_pos[valid] = pos;
      sample_frame[valid] = frame;
      valid++;
      float *s = rest + size_t(k) * stride;
      copy_v3_v3(s, pos);
      copy_v3_v3(s + 3, frame[0]);
      copy_v3_v3(s + 6, frame[1]);
      copy_v3_v3(s + 9, frame[2]);
    }
    else if (k > 0) {
      /* Carry the previous entry forward so a gap never leaves a zero (i.e. singular) frame for
       * the deformer to invert. */
      memcpy(rest + size_t(k) * stride, rest + size_t(k - 1) * stride, sizeof(float) * stride);
    }
  }
  if (valid == 0) {
    MEM_freeN(rest);
    BKE_report(reports, RPT_ERROR, "Curve has no evaluated path to bind to");
    return false;
  }
  /* A leading gap kept its zeros above (nothing to carry forward from); backfill it from the
   * first entry that did sample. */
  int first_valid = 0;
  while (first_valid < sample_count && is_zero_v3(rest + size_t(first_valid) * stride + 3)) {
    first_valid++;
  }
  for (int k = 0; k < first_valid && first_valid < sample_count; k++) {
    memcpy(rest + size_t(k) * stride, rest + size_t(first_valid) * stride, sizeof(float) * stride);
  }
  for (GreasePencilDrawingBase *base : grease_pencil.drawings()) {
    if (base->type != GP_DRAWING) {
      continue;
    }
    bke::greasepencil::Drawing &drawing = reinterpret_cast<GreasePencilDrawing *>(base)->wrap();
    bke::CurvesGeometry &curves = drawing.strokes_for_write();
    if (curves.points_num() == 0) {
      continue;
    }
    const Span<float3> positions = curves.positions();
    bke::MutableAttributeAccessor attributes = curves.attributes_for_write();
    attributes.remove(greasepencil_curve::ATTR_U);
    attributes.remove(greasepencil_curve::ATTR_OFFSET);
    attributes.remove(greasepencil_curve::ATTR_BOUND);
    bke::SpanAttributeWriter<float> w_u = attributes.lookup_or_add_for_write_only_span<float>(
        greasepencil_curve::ATTR_U, bke::AttrDomain::Point);
    bke::SpanAttributeWriter<float3> w_off = attributes.lookup_or_add_for_write_only_span<float3>(
        greasepencil_curve::ATTR_OFFSET, bke::AttrDomain::Point);
    /* Marks these points as the ones the binding covers. Points added later default to false, so
     * the deformer knows to leave them alone instead of reading a `u` of 0 they never got. */
    bke::SpanAttributeWriter<bool> w_bound = attributes.lookup_or_add_for_write_only_span<bool>(
        greasepencil_curve::ATTR_BOUND, bke::AttrDomain::Point);
    w_bound.span.fill(true);
    for (const int64_t i : positions.index_range()) {
      const float3 q = math::transform_point(gp_to_curve, positions[i]);
      int best = 0;
      float best_dist = math::distance_squared(q, sample_pos[0]);
      for (int k = 1; k < valid; k++) {
        const float d = math::distance_squared(q, sample_pos[k]);
        if (d < best_dist) {
          best_dist = d;
          best = k;
        }
      }
      /* Store the point's offset in the curve frame at its nearest arc-length param, so the
       * deformer can rebuild it on the posed curve (rest pose stays identical). */
      w_u.span[i] = sample_u[best];
      w_off.span[i] = math::transpose(sample_frame[best]) * (q - sample_pos[best]);
    }
    w_u.finish();
    w_off.finish();
    w_bound.finish();
  }
  /* Hand the sampled rest curve to the modifier: it is what lets the deformer measure each point's
   * offset against the LIVE drawing on every evaluation, instead of replaying the snapshot written
   * above (which is kept only so a build without this can still open the file). */
  MEM_SAFE_FREE(cmd->rest_samples);
  cmd->rest_samples = rest;
  cmd->rest_samples_num = sample_count;
  copy_m4_m4(cmd->rest_gp_to_curve, reinterpret_cast<const float (*)[4]>(gp_to_curve.ptr()));

  /* The curve's current shape is now the rest pose; snapshot it so Reset can return here after the
   * artist bends the curve. */
  curve_store_rest(curve_ob);
  return true;
}

static wmOperatorStatus greasepencil_curve_bind_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  GreasePencilCurveModifierData *cmd = (GreasePencilCurveModifierData *)edit_modifier_property_get(
      op, ob, eModifierType_GreasePencilCurve);

  if (cmd == nullptr || ob->type != OB_GREASE_PENCIL) {
    return OPERATOR_CANCELLED;
  }
  const bool unbind = RNA_boolean_get(op->ptr, "unbind");

  /* Ensure the deform curve is parented to the drawing, so it tracks every motion of the object -
   * and the binding stays valid. Curves built by the setup operator already are; this self-heals
   * older/hand-made curves on (re)bind. The world-preserving parentinv keeps the curve from
   * jumping, so the binding sampled below is unchanged.
   *
   * A curve that already carries a Follow Peg constraint is skipped: it tracks the rig on its own,
   * and parenting it to a drawing that follows the same peg transforms it TWICE. That is invisible
   * at rest and doubles every move the moment the peg is posed (measured: the peg moves 1.0 and
   * the drawing moves 2.0), which reads as the piece distorting on its own. */
  if (!unbind && cmd->object != nullptr && cmd->object->parent != ob &&
      !object_follows_peg(cmd->object))
  {
    Main *bmain = CTX_data_main(C);
    cmd->object->parent = ob;
    cmd->object->partype = PAROBJECT;
    const blender::float4x4 parentinv = blender::math::invert(ob->object_to_world());
    copy_m4_m4(cmd->object->parentinv, reinterpret_cast<const float (*)[4]>(parentinv.ptr()));
    DEG_relations_tag_update(bmain);
    DEG_id_tag_update(&cmd->object->id, ID_RECALC_TRANSFORM | ID_RECALC_GEOMETRY);
  }

  if (!greasepencil_curve_bind_drawings(depsgraph, ob, cmd, unbind, op->reports)) {
    return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus greasepencil_curve_bind_invoke(bContext *C,
                                                       wmOperator *op,
                                                       const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return greasepencil_curve_bind_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_greasepencil_curve_bind(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Curve Deform Bind";
  ot->description =
      "Bind the Grease Pencil drawing to the deform curve in its current (rest) pose, so the "
      "curve can sit on the drawing and deform from there";
  ot->idname = "OBJECT_OT_greasepencil_curve_bind";

  /* API callbacks. */
  ot->poll = greasepencil_curve_bind_poll;
  ot->invoke = greasepencil_curve_bind_invoke;
  ot->exec = greasepencil_curve_bind_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
  RNA_def_boolean(ot->srna, "unbind", false, "Unbind", "Remove the rest-pose binding instead");
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Grease Pencil Curve Deform Setup Operator
 *
 * One-click helper for 2D animators: builds a bezier curve fitted to the active drawing and
 * assigns it to the Curve modifier (left unbound), replacing the manual "create curve -> align ->
 * assign" dance. The artist then shapes the curve over the drawing and presses Bind to Rest Pose.
 * \{ */

/* Create a legacy bezier curve object spanning the drawing horizontally, lying in the drawing
 * plane (GP local XZ; local Y is the drawing normal). Returns the new object (already active and
 * selected via add_type), or null on failure. */
/* Custom-property key holding the Deform Curve's rest control points (flat float array, 9 per
 * Bezier point: the 3 vectors x,y,z). Stamped at curve creation and refreshed on Bind, so the
 * Reset operator can send the edited curve back to the bound rest shape. */
#define CURVE_REST_PROP "nuclear_curve_rest"

/* Snapshot the first Bezier spline of `curve_ob`'s (object-mode) data as its rest pose. */
static void curve_store_rest(Object *curve_ob)
{
  if (curve_ob == nullptr || curve_ob->type != OB_CURVES_LEGACY) {
    return;
  }
  const Curve *cu = static_cast<const Curve *>(curve_ob->data);
  const Nurb *nu = static_cast<const Nurb *>(cu->nurb.first);
  if (nu == nullptr || nu->type != CU_BEZIER || nu->bezt == nullptr || nu->pntsu < 1) {
    return;
  }
  const int n = nu->pntsu;
  IDProperty *group = IDP_EnsureProperties(&curve_ob->id);
  IDPropertyTemplate val = {};
  val.array.len = n * 9;
  val.array.type = IDP_FLOAT;
  IDProperty *prop = IDP_New(IDP_ARRAY, &val, CURVE_REST_PROP);
  float *d = IDP_array_float_get(prop);
  for (int i = 0; i < n; i++) {
    const BezTriple &b = nu->bezt[i];
    copy_v3_v3(d + (i * 9 + 0), b.vec[0]);
    copy_v3_v3(d + (i * 9 + 3), b.vec[1]);
    copy_v3_v3(d + (i * 9 + 6), b.vec[2]);
  }
  IDP_ReplaceInGroup(group, prop);
}

static Object *greasepencil_curve_create_for_drawing(bContext *C, Object *ob, ReportList *reports)
{
  GreasePencil &grease_pencil = *static_cast<GreasePencil *>(ob->data);

  /* Union bounding box of every stroke point, in GP-local space. */
  float3 bb_min(std::numeric_limits<float>::max());
  float3 bb_max(std::numeric_limits<float>::lowest());
  bool has_points = false;
  for (GreasePencilDrawingBase *base : grease_pencil.drawings()) {
    if (base->type != GP_DRAWING) {
      continue;
    }
    const bke::greasepencil::Drawing &drawing =
        reinterpret_cast<GreasePencilDrawing *>(base)->wrap();
    for (const float3 &p : drawing.strokes().positions()) {
      bb_min = math::min(bb_min, p);
      bb_max = math::max(bb_max, p);
      has_points = true;
    }
  }
  if (!has_points) {
    BKE_report(reports, RPT_ERROR, "Grease Pencil has no points to fit a curve to");
    return nullptr;
  }

  const float3 center = (bb_min + bb_max) * 0.5f;
  const float x0 = bb_min.x;
  const float x1 = bb_max.x;
  /* Guard a zero-width drawing so the handles are not degenerate. */
  const float width = std::max(x1 - x0, 1e-4f);

  Object *curve_ob = add_type(C, OB_CURVES_LEGACY, "Deform Curve", ob->loc, ob->rot, false, 0);

  /* Parent the curve to the Grease Pencil with an identity local transform. This makes curve-local
   * space exactly GP-local space, so the fitted control points sit on the drawing and the bind's
   * GP->curve mapping stays an identity rest pose. Parenting also makes the curve track every
   * motion of the drawing object - including a Follow Peg constraint - so moving a peg carries the
   * deform curve along and the arc-length binding remains valid. */
  curve_ob->parent = ob;
  curve_ob->partype = PAROBJECT;
  zero_v3(curve_ob->loc);
  zero_v3(curve_ob->rot);
  unit_qt(curve_ob->quat);
  copy_v3_fl(curve_ob->scale, 1.0f);
  unit_m4(curve_ob->parentinv);
  curve_ob->rotmode = ob->rotmode;

  Curve *cu = static_cast<Curve *>(curve_ob->data);
  /* 3D so the path keeps the drawing-plane (Z) offsets instead of flattening them. */
  cu->flag |= CU_3D;

  const int points_num = 3;
  Nurb *nu = MEM_callocN<Nurb>(__func__);
  nu->type = CU_BEZIER;
  nu->resolu = 12;
  nu->pntsu = points_num;
  nu->pntsv = 1;
  nu->bezt = MEM_calloc_arrayN<BezTriple>(points_num, __func__);
  for (int i = 0; i < points_num; i++) {
    BezTriple *bezt = &nu->bezt[i];
    const float t = float(i) / float(points_num - 1);
    const float x = x0 + (x1 - x0) * t;
    /* Spread the handles along X; BKE_nurb_handles_calc then refines them to a smooth line. */
    const float hx = width / float(points_num - 1) * 0.3f;
    bezt->vec[0][0] = x - hx;
    bezt->vec[1][0] = x;
    bezt->vec[2][0] = x + hx;
    for (int h = 0; h < 3; h++) {
      bezt->vec[h][1] = center.y;
      bezt->vec[h][2] = center.z;
    }
    bezt->h1 = bezt->h2 = HD_AUTO;
    bezt->f1 = bezt->f2 = bezt->f3 = SELECT;
    bezt->radius = 1.0f;
    bezt->weight = 1.0f;
  }
  BLI_addtail(&cu->nurb, nu);
  BKE_nurb_handles_calc(nu);

  /* Remember the freshly-fitted shape as the rest pose (refreshed again on Bind). */
  curve_store_rest(curve_ob);

  return curve_ob;
}

/* True when any drawing of the Grease Pencil object has at least one stroke point, i.e. there is
 * something to fit a deform curve to. */
static bool greasepencil_has_any_point(const Object *ob)
{
  const GreasePencil &grease_pencil = *static_cast<const GreasePencil *>(ob->data);
  for (const GreasePencilDrawingBase *base : grease_pencil.drawings()) {
    if (base->type != GP_DRAWING) {
      continue;
    }
    const bke::greasepencil::Drawing &drawing =
        reinterpret_cast<const GreasePencilDrawing *>(base)->wrap();
    if (!drawing.strokes().positions().is_empty()) {
      return true;
    }
  }
  return false;
}

/* Build a deform curve fitted to `ob`'s drawing and assign it to `cmd` (left unbound), keeping the
 * Grease Pencil the active object. Shared by the one-click "Add Deform Curve" button and the
 * auto-setup performed when the modifier is added through the Add Modifier menu. Returns false
 * (and may report) when the curve could not be built, e.g. the drawing has no points yet. */
static bool greasepencil_curve_create_and_assign(bContext *C,
                                                 Main *bmain,
                                                 Scene *scene,
                                                 Object *ob,
                                                 GreasePencilCurveModifierData *cmd,
                                                 ReportList *reports)
{
  Object *curve_ob = greasepencil_curve_create_for_drawing(C, ob, reports);
  if (curve_ob == nullptr) {
    return false;
  }
  cmd->object = curve_ob;
  cmd->deform_axis = MOD_CURVE_POSX;

  /* add_type() made the new curve the active object; re-activate the Grease Pencil so its modifier
   * panel (with the Bind button) stays in view. The curve stays selected, so the artist can still
   * click it to shape it before binding. */
  ViewLayer *view_layer = CTX_data_view_layer(C);
  BKE_view_layer_synced_ensure(scene, view_layer);
  if (Base *gp_base = BKE_view_layer_base_find(view_layer, ob)) {
    base_activate(C, gp_base);
    /* base_activate() only refreshes the data; without this notifier the Properties editor keeps
     * showing the freshly added curve (which add_type made active) instead of the Grease Pencil,
     * so the new modifier would appear to be missing from the drawing object. */
    WM_event_add_notifier(C, NC_SCENE | ND_OB_ACTIVE, scene);
  }

  /* Intentionally left *unbound*: the artist positions and shapes the curve over the drawing
   * first, then presses "Bind to Rest Pose". Until bound the modifier is a pass-through, so the
   * drawing is not influenced while the curve is being placed. Register the new object and its
   * modifier relation so the curve shows up and can be edited right away. */
  DEG_relations_tag_update(bmain);
  DEG_id_tag_update(&curve_ob->id, ID_RECALC_TRANSFORM | ID_RECALC_GEOMETRY);
  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  WM_event_add_notifier(C, NC_OBJECT | ND_DRAW, curve_ob);
  return true;
}

static wmOperatorStatus greasepencil_curve_setup_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  Object *ob = context_active_object(C);

  if (ob == nullptr || ob->type != OB_GREASE_PENCIL) {
    return OPERATOR_CANCELLED;
  }

  /* Reuse the modifier the button belongs to, or add a fresh one when invoked without one. */
  GreasePencilCurveModifierData *cmd = (GreasePencilCurveModifierData *)edit_modifier_property_get(
      op, ob, eModifierType_GreasePencilCurve);
  if (cmd == nullptr) {
    cmd = (GreasePencilCurveModifierData *)modifier_add(
        op->reports, bmain, scene, ob, nullptr, eModifierType_GreasePencilCurve);
    if (cmd == nullptr) {
      return OPERATOR_CANCELLED;
    }
  }
  if (cmd->object != nullptr) {
    BKE_report(op->reports, RPT_ERROR, "The modifier already has a curve assigned");
    return OPERATOR_CANCELLED;
  }

  if (!greasepencil_curve_create_and_assign(C, bmain, scene, ob, cmd, op->reports)) {
    return OPERATOR_CANCELLED;
  }
  BKE_report(op->reports,
             RPT_INFO,
             "Created a deform curve - shape it over the drawing, then press Bind to Rest Pose");
  return OPERATOR_FINISHED;
}

static wmOperatorStatus greasepencil_curve_setup_invoke(bContext *C,
                                                        wmOperator *op,
                                                        const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return greasepencil_curve_setup_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_greasepencil_curve_setup(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Add Deform Curve";
  ot->description =
      "Create a bezier curve fitted to the drawing and assign it to this modifier, leaving it "
      "unbound so it can be shaped over the drawing before binding";
  ot->idname = "OBJECT_OT_greasepencil_curve_setup";

  /* API callbacks. */
  ot->poll = greasepencil_curve_bind_poll;
  ot->invoke = greasepencil_curve_setup_invoke;
  ot->exec = greasepencil_curve_setup_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Grease Pencil Curve Deform Reset Operator
 *
 * Sends the Deform Curve's Bezier control points back to the rest shape snapshotted at creation /
 * Bind, so the curve deform returns to a no-op. "All" resets the whole curve; "Selected" resets only
 * the selected control points (a selected knot resets its handles too) - the natural per-point reset
 * while shaping the curve in Edit Mode. Bound to Alt+R (Object Mode on the curve, and Curve Edit
 * Mode for the selected case); non-curve objects fall through to native Alt+R.
 * \{ */

enum {
  CURVE_RESET_ALL = 0,
  CURVE_RESET_SELECTED = 1,
};

/* Resolve the Deform Curve to reset: the active object when it is the curve itself (Object/Edit
 * Mode on it), otherwise the curve assigned to the active Grease Pencil's Curve modifier (panel
 * button). Returns null when neither applies. */
static Object *curve_reset_target(bContext *C, wmOperator *op)
{
  Object *active = context_active_object(C);
  if (active == nullptr) {
    return nullptr;
  }
  if (active->type == OB_CURVES_LEGACY) {
    return active;
  }
  if (active->type == OB_GREASE_PENCIL) {
    auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(
        edit_modifier_property_get(op, active, eModifierType_GreasePencilCurve));
    if (cmd == nullptr) {
      cmd = reinterpret_cast<GreasePencilCurveModifierData *>(
          BKE_modifiers_findby_type(active, eModifierType_GreasePencilCurve));
    }
    return cmd ? cmd->object : nullptr;
  }
  return nullptr;
}

static bool greasepencil_curve_reset_poll(bContext *C)
{
  Object *ob = context_active_object(C);
  if (ob == nullptr) {
    return false;
  }
  if (ob->type == OB_CURVES_LEGACY) {
    return ob->id.properties != nullptr &&
           IDP_GetPropertyTypeFromGroup(ob->id.properties, CURVE_REST_PROP, IDP_ARRAY) != nullptr;
  }
  return ob->type == OB_GREASE_PENCIL &&
         BKE_modifiers_findby_type(ob, eModifierType_GreasePencilCurve) != nullptr;
}

static wmOperatorStatus greasepencil_curve_reset_exec(bContext *C, wmOperator *op)
{
  const int mode = RNA_enum_get(op->ptr, "mode");
  Object *curve_ob = curve_reset_target(C, op);
  if (curve_ob == nullptr || curve_ob->type != OB_CURVES_LEGACY) {
    BKE_report(op->reports, RPT_ERROR, "No Deform Curve to reset on the active object");
    return OPERATOR_CANCELLED;
  }

  Curve *cu = static_cast<Curve *>(curve_ob->data);
  const IDProperty *prop = (curve_ob->id.properties != nullptr) ?
                               IDP_GetPropertyTypeFromGroup(
                                   curve_ob->id.properties, CURVE_REST_PROP, IDP_ARRAY) :
                               nullptr;
  if (prop == nullptr || prop->subtype != IDP_FLOAT || prop->len < 9) {
    BKE_report(op->reports, RPT_ERROR, "This curve has no stored rest pose (create or bind it first)");
    return OPERATOR_CANCELLED;
  }
  const float *rest = IDP_array_float_get(const_cast<IDProperty *>(prop));
  const int rest_points = prop->len / 9;

  /* Edits in Curve Edit Mode live in the edit-nurbs copy; Object Mode uses the base curve. */
  ListBase *nurbs = (cu->editnurb != nullptr) ? BKE_curve_editNurbs_get(cu) : &cu->nurb;
  Nurb *nu = (nurbs != nullptr) ? static_cast<Nurb *>(nurbs->first) : nullptr;
  if (nu == nullptr || nu->type != CU_BEZIER || nu->bezt == nullptr) {
    return OPERATOR_CANCELLED;
  }

  const int n = std::min(nu->pntsu, rest_points);
  int reset_num = 0;
  for (int i = 0; i < n; i++) {
    BezTriple &b = nu->bezt[i];
    const float *r = rest + i * 9;
    if (mode == CURVE_RESET_ALL) {
      copy_v3_v3(b.vec[0], r + 0);
      copy_v3_v3(b.vec[1], r + 3);
      copy_v3_v3(b.vec[2], r + 6);
      reset_num++;
    }
    else if (b.f2 & SELECT) {
      /* Knot selected: reset the whole point (anchor + both handles). */
      copy_v3_v3(b.vec[0], r + 0);
      copy_v3_v3(b.vec[1], r + 3);
      copy_v3_v3(b.vec[2], r + 6);
      reset_num++;
    }
    else {
      /* Otherwise reset only the individually selected handle(s). */
      if (b.f1 & SELECT) {
        copy_v3_v3(b.vec[0], r + 0);
        reset_num++;
      }
      if (b.f3 & SELECT) {
        copy_v3_v3(b.vec[2], r + 6);
        reset_num++;
      }
    }
  }

  if (mode == CURVE_RESET_SELECTED && reset_num == 0) {
    /* Nothing selected on the curve: let native Alt+R run instead of consuming the event. */
    return OPERATOR_PASS_THROUGH;
  }
  if (reset_num == 0) {
    return OPERATOR_CANCELLED;
  }

  /* Tag the curve DATA (not just the object): in Edit Mode this is what rebuilds the cage batch
   * cache so the reset is actually drawn, and it propagates to the dependent Grease Pencil deform
   * through the depsgraph. */
  DEG_id_tag_update(&cu->id, ID_RECALC_GEOMETRY);
  DEG_id_tag_update(&curve_ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_GEOM | ND_DATA, &cu->id);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, curve_ob);
  /* When triggered from the Grease Pencil's modifier panel, also tag the drawing so its Curve
   * deform re-evaluates immediately (not only on the next depsgraph cascade). */
  Object *active = context_active_object(C);
  if (active != nullptr && active->type == OB_GREASE_PENCIL) {
    DEG_id_tag_update(&active->id, ID_RECALC_GEOMETRY);
    WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, active);
  }
  return OPERATOR_FINISHED;
}

static wmOperatorStatus greasepencil_curve_reset_invoke(bContext *C,
                                                        wmOperator *op,
                                                        const wmEvent * /*event*/)
{
  Object *active = context_active_object(C);
  /* Panel button (Grease Pencil active) needs the modifier the panel points at. */
  if (active != nullptr && active->type == OB_GREASE_PENCIL) {
    edit_modifier_invoke_properties(C, op);
  }
  return greasepencil_curve_reset_exec(C, op);
}

void OBJECT_OT_greasepencil_curve_reset(wmOperatorType *ot)
{
  static const EnumPropertyItem mode_items[] = {
      {CURVE_RESET_ALL, "ALL", 0, "All", "Reset the whole Deform Curve to its rest shape"},
      {CURVE_RESET_SELECTED,
       "SELECTED",
       0,
       "Selected",
       "Reset only the selected control points (a selected knot also resets its handles)"},
      {0, nullptr, 0, nullptr, nullptr},
  };

  ot->name = "Reset Deform Curve";
  ot->description = "Send the Deform Curve's control points back to their rest shape";
  ot->idname = "OBJECT_OT_greasepencil_curve_reset";

  ot->poll = greasepencil_curve_reset_poll;
  ot->invoke = greasepencil_curve_reset_invoke;
  ot->exec = greasepencil_curve_reset_exec;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
  RNA_def_enum(ot->srna,
               "mode",
               mode_items,
               CURVE_RESET_SELECTED,
               "Mode",
               "Which control points to send back to rest");
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Grease Pencil Contour (Envelope) Bind Operator
 * \{ */

static bool greasepencil_contour_bind_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_GreasePencilContourModifier, 0, true, false);
}

/* Store (or clear, when `unbind`) the rest contour of the Contour modifier's cage, so editing the
 * cage afterwards deforms the art from this snapshot. Returns false (and reports) on failure. */
static bool greasepencil_contour_bind_modifier(Depsgraph *depsgraph,
                                               Object *ob,
                                               GreasePencilContourModifierData *cmd,
                                               const bool unbind,
                                               ReportList *reports)
{
  MEM_SAFE_FREE(cmd->bind_co);
  cmd->bind_verts_num = 0;
  cmd->flag &= ~MOD_GREASE_PENCIL_CONTOUR_BOUND;
  if (unbind) {
    return true;
  }
  blender::Vector<blender::float3> contour;
  if (cmd->cage_layer[0] != '\0') {
    /* Nuclear: layer-cage. Capture the cage layer's first stroke (of this Grease Pencil object) as
     * the rest contour, so editing that stroke afterwards deforms the rest of the drawing. */
    const Object *ob_eval = DEG_get_evaluated(depsgraph, ob);
    const GreasePencil *gp_eval = (ob_eval != nullptr && ob_eval->type == OB_GREASE_PENCIL) ?
                                      static_cast<const GreasePencil *>(ob_eval->data) :
                                      nullptr;
    const int frame = (gp_eval != nullptr && gp_eval->runtime != nullptr) ?
                          gp_eval->runtime->eval_frame :
                          0;
    if (gp_eval == nullptr ||
        !blender::modifier::greasepencil::contour_sample_gp_layer(
            *gp_eval, cmd->cage_layer, frame, contour))
    {
      BKE_report(reports,
                 RPT_ERROR,
                 "Guide line layer has no usable stroke (it needs at least one drawn stroke)");
      return false;
    }
  }
  else {
    if (cmd->object == nullptr) {
      BKE_report(reports, RPT_ERROR, "Assign a cage object or a cage layer before binding");
      return false;
    }
    const Object *cage_eval = DEG_get_evaluated(depsgraph, cmd->object);
    if (cage_eval == nullptr ||
        !blender::modifier::greasepencil::contour_sample_cage(*cage_eval, true, contour))
    {
      BKE_report(reports,
                 RPT_ERROR,
                 "Cage has no usable contour (need a mesh ring or a cyclic Bezier spline)");
      return false;
    }
  }
  cmd->bind_co = MEM_malloc_arrayN<float[3]>(size_t(contour.size()), __func__);
  for (const int i : contour.index_range()) {
    copy_v3_v3(cmd->bind_co[i], contour[i]);
  }
  cmd->bind_verts_num = contour.size();
  cmd->flag |= MOD_GREASE_PENCIL_CONTOUR_BOUND;
  return true;
}

static wmOperatorStatus greasepencil_contour_bind_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  GreasePencilContourModifierData *cmd = (GreasePencilContourModifierData *)
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilContour);

  if (cmd == nullptr || ob->type != OB_GREASE_PENCIL) {
    return OPERATOR_CANCELLED;
  }
  const bool unbind = RNA_boolean_get(op->ptr, "unbind");
  if (!greasepencil_contour_bind_modifier(depsgraph, ob, cmd, unbind, op->reports)) {
    return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus greasepencil_contour_bind_invoke(bContext *C,
                                                         wmOperator *op,
                                                         const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return greasepencil_contour_bind_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_greasepencil_contour_bind(wmOperatorType *ot)
{
  ot->name = "Contour Bind";
  ot->description =
      "Capture the cage's current contour as the rest pose, so editing the cage (e.g. a Bezier "
      "envelope) deforms the drawing from there";
  ot->idname = "OBJECT_OT_greasepencil_contour_bind";

  ot->poll = greasepencil_contour_bind_poll;
  ot->invoke = greasepencil_contour_bind_invoke;
  ot->exec = greasepencil_contour_bind_exec;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
  RNA_def_boolean(ot->srna, "unbind", false, "Unbind", "Remove the rest binding instead");
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Grease Pencil Envelope Setup Operator
 *
 * One click for 2D animators: traces a cyclic Bezier curve around the drawing's silhouette,
 * assigns it to the Contour modifier and binds it. The artist then reshapes the Bezier (anchors +
 * handles) directly and the art deforms like a Toon Boom envelope.
 * \{ */

/* Build a cyclic Bezier curve hugging the convex silhouette of `ob`'s drawing, lying in the
 * drawing plane, parented to the drawing with an identity local transform. Returns the new curve
 * object (active/selected) or null on failure. */
static Object *greasepencil_envelope_create_for_drawing(bContext *C,
                                                        Object *ob,
                                                        ReportList *reports)
{
  using namespace blender;
  const GreasePencil &grease_pencil = *static_cast<const GreasePencil *>(ob->data);

  Vector<float3> pts;
  float3 bb_min(std::numeric_limits<float>::max());
  float3 bb_max(std::numeric_limits<float>::lowest());
  for (const GreasePencilDrawingBase *base : grease_pencil.drawings()) {
    if (base->type != GP_DRAWING) {
      continue;
    }
    const bke::greasepencil::Drawing &drawing =
        reinterpret_cast<const GreasePencilDrawing *>(base)->wrap();
    for (const float3 &p : drawing.strokes().positions()) {
      pts.append(p);
      bb_min = math::min(bb_min, p);
      bb_max = math::max(bb_max, p);
    }
  }
  if (pts.size() < 3) {
    BKE_report(reports, RPT_ERROR, "Grease Pencil has no points to fit an envelope to");
    return nullptr;
  }

  /* Working plane = the two largest-extent axes (the drawing is flat along the third). */
  const float3 ext = bb_max - bb_min;
  int an = 0;
  if (ext[1] < ext[an]) {
    an = 1;
  }
  if (ext[2] < ext[an]) {
    an = 2;
  }
  const int au = (an + 1) % 3;
  const int av = (an + 2) % 3;
  const float normal_co = (bb_min[an] + bb_max[an]) * 0.5f;

  Vector<float2> pts2(pts.size());
  for (const int i : pts.index_range()) {
    pts2[i] = float2(pts[i][au], pts[i][av]);
  }
  Array<int> hull(pts2.size());
  const int hull_num = BLI_convexhull_2d(pts2.as_span(), hull.data());
  if (hull_num < 3) {
    BKE_report(reports, RPT_ERROR, "Could not build a silhouette from the drawing");
    return nullptr;
  }

  /* Keep the envelope editable: cap to a handful of anchors, evenly spaced around the hull. */
  const int max_anchors = 6;
  const int anchors_num = std::min(hull_num, max_anchors);
  float2 centroid(0.0f, 0.0f);
  for (const int k : IndexRange(hull_num)) {
    centroid += pts2[hull[k]];
  }
  centroid /= float(hull_num);
  const float margin = 1.08f; /* push the contour slightly outside the art so it sits inside */

  Object *curve_ob = add_type(C, OB_CURVES_LEGACY, "Envelope", ob->loc, ob->rot, false, 0);
  curve_ob->parent = ob;
  curve_ob->partype = PAROBJECT;
  zero_v3(curve_ob->loc);
  zero_v3(curve_ob->rot);
  unit_qt(curve_ob->quat);
  copy_v3_fl(curve_ob->scale, 1.0f);
  unit_m4(curve_ob->parentinv);
  curve_ob->rotmode = ob->rotmode;

  Curve *cu = static_cast<Curve *>(curve_ob->data);
  cu->flag |= CU_3D;
  /* Thin bevel so the envelope reads as a drawn Bezier line (like a native curve), not an
   * invisible path. The Contour samples `deformed_nurbs`, which is built before the bevel's mesh
   * conversion, so this does not affect the deformation. */
  cu->bevel_radius = 0.008f;

  Nurb *nu = MEM_callocN<Nurb>(__func__);
  nu->type = CU_BEZIER;
  nu->resolu = 12;
  nu->pntsu = anchors_num;
  nu->pntsv = 1;
  nu->flagu = CU_NURB_CYCLIC;
  nu->bezt = MEM_calloc_arrayN<BezTriple>(anchors_num, __func__);
  for (const int k : IndexRange(anchors_num)) {
    const int hk = hull[(k * hull_num) / anchors_num];
    const float2 a = centroid + (pts2[hk] - centroid) * margin;
    BezTriple *bezt = &nu->bezt[k];
    for (int h = 0; h < 3; h++) {
      bezt->vec[h][au] = a.x;
      bezt->vec[h][av] = a.y;
      bezt->vec[h][an] = normal_co;
    }
    bezt->h1 = bezt->h2 = HD_AUTO;
    bezt->f1 = bezt->f2 = bezt->f3 = SELECT;
    bezt->radius = 1.0f;
    bezt->weight = 1.0f;
  }
  BLI_addtail(&cu->nurb, nu);
  BKE_nurb_handles_calc(nu);
  /* Freeze the auto-computed handles as FREE so the per-handle controls can bend the tangents
   * without the handle solver pulling them back. */
  for (const int k : blender::IndexRange(anchors_num)) {
    nu->bezt[k].h1 = nu->bezt[k].h2 = HD_FREE;
  }

  return curve_ob;
}

/* Hide/show an object in the view layer via its base (the "eye" toggle). Keeps the object evaluated
 * — so a hidden cage curve still deforms — it only stops drawing/selecting it. */
static void envelope_base_set_hidden(Scene *scene, ViewLayer *view_layer, Object *ob, const bool hide)
{
  BKE_view_layer_synced_ensure(scene, view_layer);
  Base *base = BKE_view_layer_base_find(view_layer, ob);
  if (base == nullptr) {
    return;
  }
  if (hide) {
    base->flag |= BASE_HIDDEN;
  }
  else {
    base->flag &= ~BASE_HIDDEN;
  }
  BKE_view_layer_need_resync_tag(view_layer);
}

/* Custom-property key tagging a controller Empty with its rest local location. Presence of the
 * property both stores the home pose (for the Reset operator) and marks the object as an
 * envelope/spine controller (so the Reset keymap can leave non-controllers to native Alt+R). */
#define ENVELOPE_REST_PROP "nuclear_envelope_rest"

/* Stamp `emp` with its rest local location so the Reset operator can send it home. */
static void envelope_store_rest(Object *emp, const blender::float3 &rest_loc)
{
  IDProperty *group = IDP_EnsureProperties(&emp->id);
  IDPropertyTemplate val = {};
  val.array.len = 3;
  val.array.type = IDP_FLOAT;
  IDProperty *prop = IDP_New(IDP_ARRAY, &val, ENVELOPE_REST_PROP);
  float *data = IDP_array_float_get(prop);
  copy_v3_v3(data, rest_loc);
  IDP_ReplaceInGroup(group, prop);
}

/* Read a controller Empty's stored rest local location into `r_rest`. Returns false when the
 * object carries no (valid) rest property, i.e. it is not an envelope/spine controller. */
static bool envelope_get_rest(const Object *emp, blender::float3 &r_rest)
{
  if (emp->id.properties == nullptr) {
    return false;
  }
  IDProperty *prop = IDP_GetPropertyTypeFromGroup(emp->id.properties, ENVELOPE_REST_PROP, IDP_ARRAY);
  if (prop == nullptr || prop->subtype != IDP_FLOAT || prop->len != 3) {
    return false;
  }
  copy_v3_v3(r_rest, IDP_array_float_get(prop));
  return true;
}

/* Create one control Empty parented to `parent`, sitting on the cage point `cage_vec`
 * (curve-local), plus a Hook on `curve_ob` binding the single control point `index` to it. The
 * curve and the whole control chain are identity-parented to the drawing, so the hook's
 * `parentinv` is just T(-cage_vec) and the empty's local loc is its offset from its parent.
 * Returns the empty. */
static Object *envelope_add_hook(Main *bmain,
                                 Scene *scene,
                                 ViewLayer *view_layer,
                                 Object *curve_ob,
                                 Object *parent,
                                 const blender::float3 &local_loc,
                                 const blender::float3 &cage_vec,
                                 const int index,
                                 const int drawtype,
                                 const float size,
                                 const char *name,
                                 const blender::float3 &color)
{
  Object *emp = BKE_object_add(bmain, scene, view_layer, OB_EMPTY, name);
  emp->empty_drawtype = drawtype;
  emp->empty_drawsize = size;
  emp->color[0] = color.x;
  emp->color[1] = color.y;
  emp->color[2] = color.z;
  emp->color[3] = 1.0f;
  emp->parent = parent;
  emp->partype = PAROBJECT;
  copy_v3_v3(emp->loc, local_loc);
  zero_v3(emp->rot);
  unit_qt(emp->quat);
  copy_v3_fl(emp->scale, 1.0f);
  unit_m4(emp->parentinv);
  emp->rotmode = parent->rotmode;
  /* Visual polish: draw the controls on top of the drawing and only allow translation, so the rig
   * reads as 2D handles and can't be accidentally rotated/scaled. */
  emp->dtx |= OB_DRAW_IN_FRONT;
  emp->protectflag = OB_LOCK_ROT | OB_LOCK_ROTW | OB_LOCK_ROT4D | OB_LOCK_SCALE;
  /* Remember the home pose so the Reset operator can restore it (and mark this as a controller). */
  envelope_store_rest(emp, local_loc);

  HookModifierData *hmd = (HookModifierData *)BKE_modifier_new(eModifierType_Hook);
  BLI_addtail(&curve_ob->modifiers, hmd);
  BKE_modifier_unique_name(&curve_ob->modifiers, (ModifierData *)hmd);
  BKE_modifiers_persistent_uid_init(*curve_ob, hmd->modifier);
  hmd->object = emp;
  hmd->force = 1.0f;
  hmd->falloff = 0.0f; /* rigid: only this control point follows the empty */
  copy_v3_v3(hmd->cent, cage_vec);
  int *indexar = MEM_malloc_arrayN<int>(1, __func__);
  indexar[0] = index;
  hmd->indexar = indexar;
  hmd->indexar_num = 1;
  /* parentinv = T(-cage_vec): the drawing transform cancels for the identity-parented chain. */
  unit_m4(hmd->parentinv);
  hmd->parentinv[3][0] = -cage_vec.x;
  hmd->parentinv[3][1] = -cage_vec.y;
  hmd->parentinv[3][2] = -cage_vec.z;

  DEG_id_tag_update(&emp->id, ID_RECALC_TRANSFORM);
  return emp;
}

/* Add full Bezier controls per anchor so the envelope is shaped in OBJECT MODE like a real Bezier:
 * an anchor empty (the knot) plus two tangent-handle empties parented to it. Grabbing the anchor
 * moves the whole point (the handles ride along); grabbing a handle bends the tangent. Each
 * control drives one spline point through a Hook (a pre-tessellation spline deformer that reaches
 * the Contour cage via `deformed_nurbs`). */
static void greasepencil_envelope_add_controls(
    Main *bmain, Scene *scene, ViewLayer *view_layer, Object *gp_ob, Object *curve_ob)
{
  using namespace blender;
  const Curve *cu = static_cast<const Curve *>(curve_ob->data);
  const Nurb *nu = static_cast<const Nurb *>(cu->nurb.first);
  if (nu == nullptr || nu->bezt == nullptr) {
    return;
  }

  /* Gather the cage and its controls under one collection so the artist can fold or hide the whole
   * rig in the outliner without touching the drawing. */
  Collection *coll = BKE_collection_add(bmain, scene->master_collection, "Envelope");
  BKE_collection_object_move(bmain, scene, coll, nullptr, curve_ob);

  const int n = nu->pntsu;
  for (const int i : IndexRange(n)) {
    const float3 hl(nu->bezt[i].vec[0]);
    const float3 knot(nu->bezt[i].vec[1]);
    const float3 hr(nu->bezt[i].vec[2]);

    /* Anchor = warm dot (like a control point); handles = cool dots (like handle lines). Small
     * sizes so they read as native Bezier points, not big gizmos. */
    const float3 anchor_color(1.0f, 0.55f, 0.1f);
    const float3 handle_color(0.25f, 0.7f, 1.0f);

    /* Anchor (knot): parented to the drawing, hooks control point 3i+1 (f2). */
    Object *anchor = envelope_add_hook(bmain,
                                       scene,
                                       view_layer,
                                       curve_ob,
                                       gp_ob,
                                       knot,
                                       knot,
                                       i * 3 + 1,
                                       OB_EMPTY_SPHERE,
                                       0.035f,
                                       "Env Anchor",
                                       anchor_color);
    /* Tangent handles: parented to the anchor (ride along), hook 3i (f1) and 3i+2 (f3). */
    Object *eh_l = envelope_add_hook(bmain,
                                     scene,
                                     view_layer,
                                     curve_ob,
                                     anchor,
                                     hl - knot,
                                     hl,
                                     i * 3,
                                     OB_CUBE,
                                     0.022f,
                                     "Env Handle",
                                     handle_color);
    Object *eh_r = envelope_add_hook(bmain,
                                     scene,
                                     view_layer,
                                     curve_ob,
                                     anchor,
                                     hr - knot,
                                     hr,
                                     i * 3 + 2,
                                     OB_CUBE,
                                     0.022f,
                                     "Env Handle",
                                     handle_color);
    BKE_collection_object_move(bmain, scene, coll, nullptr, anchor);
    BKE_collection_object_move(bmain, scene, coll, nullptr, eh_l);
    BKE_collection_object_move(bmain, scene, coll, nullptr, eh_r);
  }
}

/* Build an OPEN Bezier curve running along the spine (centerline) of `ob`'s longest stroke,
 * resampled to a handful of evenly-spaced anchors, lying in the drawing plane and identity-parented
 * to the drawing. The art follows this line (MLS), so grabbing its controls bends the drawing along
 * the stroke. Returns the new curve object or null on failure. */
static Object *greasepencil_spine_create_for_drawing(bContext *C, Object *ob, ReportList *reports)
{
  using namespace blender;
  const GreasePencil &grease_pencil = *static_cast<const GreasePencil *>(ob->data);

  /* Pick the longest stroke across all drawings as the spine. */
  Vector<float3> spine;
  float best_len = -1.0f;
  float3 bb_min(std::numeric_limits<float>::max());
  float3 bb_max(std::numeric_limits<float>::lowest());
  for (const GreasePencilDrawingBase *base : grease_pencil.drawings()) {
    if (base->type != GP_DRAWING) {
      continue;
    }
    const bke::greasepencil::Drawing &drawing =
        reinterpret_cast<const GreasePencilDrawing *>(base)->wrap();
    const bke::CurvesGeometry &curves = drawing.strokes();
    const OffsetIndices<int> by_curve = curves.points_by_curve();
    const Span<float3> positions = curves.positions();
    for (const float3 &p : positions) {
      bb_min = math::min(bb_min, p);
      bb_max = math::max(bb_max, p);
    }
    for (const int curve : curves.curves_range()) {
      const IndexRange pts = by_curve[curve];
      if (pts.size() < 2) {
        continue;
      }
      float len = 0.0f;
      for (const int i : pts.drop_front(1)) {
        len += math::distance(positions[i], positions[i - 1]);
      }
      if (len > best_len) {
        best_len = len;
        spine.clear();
        for (const int i : pts) {
          spine.append(positions[i]);
        }
      }
    }
  }
  if (spine.size() < 2 || best_len <= 0.0f) {
    BKE_report(reports, RPT_ERROR, "Grease Pencil has no line to fit a spine to");
    return nullptr;
  }

  /* Working plane = the two largest-extent axes (the drawing is flat along the third). */
  const float3 ext = bb_max - bb_min;
  int an = 0;
  if (ext[1] < ext[an]) {
    an = 1;
  }
  if (ext[2] < ext[an]) {
    an = 2;
  }
  const float normal_co = (bb_min[an] + bb_max[an]) * 0.5f;

  /* Resample the spine to evenly-spaced anchors by arc length. */
  const int max_anchors = 5;
  const int anchors_num = std::min<int>(max_anchors, std::max<int>(2, spine.size()));
  Array<float> cum(spine.size());
  cum[0] = 0.0f;
  for (const int i : IndexRange(spine.size()).drop_front(1)) {
    cum[i] = cum[i - 1] + math::distance(spine[i], spine[i - 1]);
  }
  const float total = cum[spine.size() - 1];
  Vector<float3> anchors;
  for (const int k : IndexRange(anchors_num)) {
    const float target = total * float(k) / float(anchors_num - 1);
    int seg = 1;
    while (seg < spine.size() - 1 && cum[seg] < target) {
      seg++;
    }
    const float seg_len = cum[seg] - cum[seg - 1];
    const float t = seg_len > 1e-6f ? (target - cum[seg - 1]) / seg_len : 0.0f;
    anchors.append(math::interpolate(spine[seg - 1], spine[seg], t));
  }

  Object *curve_ob = add_type(C, OB_CURVES_LEGACY, "Spine", ob->loc, ob->rot, false, 0);
  curve_ob->parent = ob;
  curve_ob->partype = PAROBJECT;
  zero_v3(curve_ob->loc);
  zero_v3(curve_ob->rot);
  unit_qt(curve_ob->quat);
  copy_v3_fl(curve_ob->scale, 1.0f);
  unit_m4(curve_ob->parentinv);
  curve_ob->rotmode = ob->rotmode;

  Curve *cu = static_cast<Curve *>(curve_ob->data);
  cu->flag |= CU_3D;
  cu->bevel_radius = 0.008f;

  Nurb *nu = MEM_callocN<Nurb>(__func__);
  nu->type = CU_BEZIER;
  nu->resolu = 12;
  nu->pntsu = anchors_num;
  nu->pntsv = 1;
  nu->flagu = 0; /* OPEN spine, not cyclic. */
  nu->bezt = MEM_calloc_arrayN<BezTriple>(anchors_num, __func__);
  for (const int k : IndexRange(anchors_num)) {
    float3 a = anchors[k];
    a[an] = normal_co;
    BezTriple *bezt = &nu->bezt[k];
    for (int h = 0; h < 3; h++) {
      copy_v3_v3(bezt->vec[h], a);
    }
    bezt->h1 = bezt->h2 = HD_AUTO;
    bezt->f1 = bezt->f2 = bezt->f3 = SELECT;
    bezt->radius = 1.0f;
    bezt->weight = 1.0f;
  }
  BLI_addtail(&cu->nurb, nu);
  BKE_nurb_handles_calc(nu);
  for (const int k : blender::IndexRange(anchors_num)) {
    nu->bezt[k].h1 = nu->bezt[k].h2 = HD_FREE;
  }
  return curve_ob;
}

static wmOperatorStatus greasepencil_spine_controllers_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  Object *ob = context_active_object(C);

  if (ob == nullptr || ob->type != OB_GREASE_PENCIL) {
    return OPERATOR_CANCELLED;
  }

  GreasePencilContourModifierData *cmd = (GreasePencilContourModifierData *)
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilContour);
  if (cmd == nullptr) {
    cmd = (GreasePencilContourModifierData *)modifier_add(
        op->reports, bmain, scene, ob, nullptr, eModifierType_GreasePencilContour);
    if (cmd == nullptr) {
      return OPERATOR_CANCELLED;
    }
  }
  if (cmd->object != nullptr || cmd->cage_layer[0] != '\0') {
    BKE_report(op->reports, RPT_ERROR, "The modifier already has a guide assigned");
    return OPERATOR_CANCELLED;
  }

  ViewLayer *view_layer = CTX_data_view_layer(C);

  Object *curve_ob = greasepencil_spine_create_for_drawing(C, ob, op->reports);
  if (curve_ob == nullptr) {
    return OPERATOR_CANCELLED;
  }
  cmd->object = curve_ob;
  /* Deform along the line (Moving Least Squares), not as a closed contour. */
  cmd->flag |= MOD_GREASE_PENCIL_CONTOUR_LINE_GUIDE;

  /* Bind to the freshly built spine (rest == its current shape), so it starts as a no-op. */
  greasepencil_contour_bind_modifier(depsgraph, ob, cmd, false, op->reports);

  /* Object-mode controls: anchor + 2 tangent empties per anchor (reused from the envelope rig), so
   * the artist bends the spine by grabbing the controls without entering Edit Mode. */
  greasepencil_envelope_add_controls(bmain, scene, view_layer, ob, curve_ob);

  /* The cage curve itself comes hidden: the artist drives it through the controllers, so the raw
   * Bezier line should not clutter the drawing (it still deforms while hidden). */
  envelope_base_set_hidden(scene, view_layer, curve_ob, true);

  BKE_view_layer_synced_ensure(scene, view_layer);
  if (Base *gp_base = BKE_view_layer_base_find(view_layer, ob)) {
    base_activate(C, gp_base);
    WM_event_add_notifier(C, NC_SCENE | ND_OB_ACTIVE, scene);
  }

  DEG_relations_tag_update(bmain);
  DEG_id_tag_update(&scene->id, ID_RECALC_BASE_FLAGS);
  DEG_id_tag_update(&curve_ob->id, ID_RECALC_TRANSFORM | ID_RECALC_GEOMETRY);
  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  WM_event_add_notifier(C, NC_OBJECT | ND_DRAW, curve_ob);
  BKE_report(op->reports,
             RPT_INFO,
             "Created spine controllers - grab the empties to bend the drawing along the line");
  return OPERATOR_FINISHED;
}

static wmOperatorStatus greasepencil_spine_controllers_invoke(bContext *C,
                                                              wmOperator *op,
                                                              const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return greasepencil_spine_controllers_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_greasepencil_spine_controllers(wmOperatorType *ot)
{
  ot->name = "Create Spine Controllers";
  ot->description =
      "Trace a Bezier curve along the centerline of the drawing's longest line, add Object-Mode "
      "controllers, and bind it so bending the line deforms the drawing";
  ot->idname = "OBJECT_OT_greasepencil_spine_controllers";

  ot->poll = greasepencil_contour_bind_poll;
  ot->invoke = greasepencil_spine_controllers_invoke;
  ot->exec = greasepencil_spine_controllers_exec;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/* Toggle the visibility of the Contour cage's Object-Mode controllers (the anchor/handle empties).
 * They are found via the cage curve's Hook modifiers, so the toggle works for both the envelope and
 * the spine rig. The cage curve stays hidden; only the controllers show/hide. */
static wmOperatorStatus greasepencil_contour_toggle_controls_exec(bContext *C, wmOperator *op)
{
  Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  Object *ob = context_active_object(C);
  GreasePencilContourModifierData *cmd = (GreasePencilContourModifierData *)
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilContour);
  if (cmd == nullptr || cmd->object == nullptr) {
    return OPERATOR_CANCELLED;
  }
  Object *curve_ob = cmd->object;

  BKE_view_layer_synced_ensure(scene, view_layer);

  /* Decide the new state from the first controller's current visibility. */
  bool any = false;
  bool currently_hidden = false;
  LISTBASE_FOREACH (ModifierData *, md, &curve_ob->modifiers) {
    if (md->type != eModifierType_Hook) {
      continue;
    }
    const HookModifierData *hmd = (const HookModifierData *)md;
    if (hmd->object == nullptr) {
      continue;
    }
    const Base *base = BKE_view_layer_base_find(view_layer, hmd->object);
    currently_hidden = base != nullptr && (base->flag & BASE_HIDDEN) != 0;
    any = true;
    break;
  }
  if (!any) {
    BKE_report(op->reports, RPT_ERROR, "This guide has no Object-Mode controllers");
    return OPERATOR_CANCELLED;
  }

  const bool hide = !currently_hidden;
  LISTBASE_FOREACH (ModifierData *, md, &curve_ob->modifiers) {
    if (md->type != eModifierType_Hook) {
      continue;
    }
    const HookModifierData *hmd = (const HookModifierData *)md;
    if (hmd->object != nullptr) {
      envelope_base_set_hidden(scene, view_layer, hmd->object, hide);
    }
  }
  DEG_id_tag_update(&scene->id, ID_RECALC_BASE_FLAGS);
  WM_event_add_notifier(C, NC_SCENE | ND_OB_SELECT, scene);
  return OPERATOR_FINISHED;
}

static wmOperatorStatus greasepencil_contour_toggle_controls_invoke(bContext *C,
                                                                    wmOperator *op,
                                                                    const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return greasepencil_contour_toggle_controls_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_greasepencil_contour_toggle_controls(wmOperatorType *ot)
{
  ot->name = "Toggle Controllers";
  ot->description = "Show or hide the Object-Mode controllers of this Contour guide";
  ot->idname = "OBJECT_OT_greasepencil_contour_toggle_controls";

  ot->poll = greasepencil_contour_bind_poll;
  ot->invoke = greasepencil_contour_toggle_controls_invoke;
  ot->exec = greasepencil_contour_toggle_controls_exec;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

static wmOperatorStatus greasepencil_envelope_setup_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);
  Scene *scene = CTX_data_scene(C);
  Depsgraph *depsgraph = CTX_data_ensure_evaluated_depsgraph(C);
  Object *ob = context_active_object(C);

  if (ob == nullptr || ob->type != OB_GREASE_PENCIL) {
    return OPERATOR_CANCELLED;
  }

  GreasePencilContourModifierData *cmd = (GreasePencilContourModifierData *)
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilContour);
  if (cmd == nullptr) {
    cmd = (GreasePencilContourModifierData *)modifier_add(
        op->reports, bmain, scene, ob, nullptr, eModifierType_GreasePencilContour);
    if (cmd == nullptr) {
      return OPERATOR_CANCELLED;
    }
  }
  if (cmd->object != nullptr) {
    BKE_report(op->reports, RPT_ERROR, "The modifier already has a cage assigned");
    return OPERATOR_CANCELLED;
  }

  ViewLayer *view_layer = CTX_data_view_layer(C);

  Object *curve_ob = greasepencil_envelope_create_for_drawing(C, ob, op->reports);
  if (curve_ob == nullptr) {
    return OPERATOR_CANCELLED;
  }
  cmd->object = curve_ob;

  /* Bind to the freshly built silhouette (its original geometry == the rest), so the envelope
   * starts as a no-op and reshaping it immediately deforms the art. */
  greasepencil_contour_bind_modifier(depsgraph, ob, cmd, false, op->reports);

  /* Object-mode controls: one Empty + Hook per anchor, so the artist grabs the empties to deform
   * without entering Edit Mode. */
  greasepencil_envelope_add_controls(bmain, scene, view_layer, ob, curve_ob);

  /* The cage curve itself comes hidden: the artist drives it through the controllers, so the raw
   * Bezier line should not clutter the drawing (it still deforms while hidden). */
  envelope_base_set_hidden(scene, view_layer, curve_ob, true);

  /* add_type()/BKE_object_add made a new object active; re-activate the Grease Pencil so its
   * modifier panel stays in view. */
  BKE_view_layer_synced_ensure(scene, view_layer);
  if (Base *gp_base = BKE_view_layer_base_find(view_layer, ob)) {
    base_activate(C, gp_base);
    WM_event_add_notifier(C, NC_SCENE | ND_OB_ACTIVE, scene);
  }

  DEG_relations_tag_update(bmain);
  DEG_id_tag_update(&scene->id, ID_RECALC_BASE_FLAGS);
  DEG_id_tag_update(&curve_ob->id, ID_RECALC_TRANSFORM | ID_RECALC_GEOMETRY);
  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  WM_event_add_notifier(C, NC_OBJECT | ND_DRAW, curve_ob);
  BKE_report(op->reports,
             RPT_INFO,
             "Created a Bezier envelope - grab the controllers to deform the drawing");
  return OPERATOR_FINISHED;
}

static wmOperatorStatus greasepencil_envelope_setup_invoke(bContext *C,
                                                           wmOperator *op,
                                                           const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return greasepencil_envelope_setup_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_greasepencil_envelope_setup(wmOperatorType *ot)
{
  ot->name = "Add Envelope";
  ot->description =
      "Trace a Bezier curve around the drawing's silhouette, assign it to this Contour modifier "
      "and bind it, ready to reshape as an envelope";
  ot->idname = "OBJECT_OT_greasepencil_envelope_setup";

  ot->poll = greasepencil_contour_bind_poll;
  ot->invoke = greasepencil_envelope_setup_invoke;
  ot->exec = greasepencil_envelope_setup_exec;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Grease Pencil Contour (Envelope/Spine) Reset Operator
 *
 * Sends the envelope/spine controllers back to the rest pose stamped on them at creation, so the
 * cage returns to its bound shape and the deform becomes a no-op again. "All" resets every
 * controller of the active drawing's guide; "Selected" resets only the selected controllers
 * (resetting an anchor also resets its two handles, which are parented to it). Bound to Alt+R in
 * Object Mode for the selected case; when the active object is not a controller the operator passes
 * the event through to native rotation-clear.
 * \{ */

enum {
  ENVELOPE_RESET_ALL = 0,
  ENVELOPE_RESET_SELECTED = 1,
};

/* Move a single controller Empty back to its stored rest local location. Returns false when the
 * object is not a controller (carries no rest property). */
static bool envelope_reset_one(Object *emp)
{
  blender::float3 rest;
  if (!envelope_get_rest(emp, rest)) {
    return false;
  }
  copy_v3_v3(emp->loc, rest);
  DEG_id_tag_update(&emp->id, ID_RECALC_TRANSFORM);
  return true;
}

static bool greasepencil_contour_reset_poll(bContext *C)
{
  Object *ob = context_active_object(C);
  if (ob == nullptr) {
    return false;
  }
  /* Controller active (keymap path) or a Grease Pencil with a Contour modifier (panel path). */
  blender::float3 rest;
  if (envelope_get_rest(ob, rest)) {
    return true;
  }
  return ob->type == OB_GREASE_PENCIL &&
         BKE_modifiers_findby_type(ob, eModifierType_GreasePencilContour) != nullptr;
}

static wmOperatorStatus greasepencil_contour_reset_exec(bContext *C, wmOperator *op)
{
  Scene *scene = CTX_data_scene(C);
  ViewLayer *view_layer = CTX_data_view_layer(C);
  Object *active = context_active_object(C);
  const int mode = RNA_enum_get(op->ptr, "mode");

  int reset_num = 0;

  if (mode == ENVELOPE_RESET_ALL) {
    /* Reset every controller of the active drawing's Contour guide (found via the cage's Hooks). */
    GreasePencilContourModifierData *cmd = (GreasePencilContourModifierData *)
        edit_modifier_property_get(op, active, eModifierType_GreasePencilContour);
    if (cmd == nullptr || cmd->object == nullptr) {
      BKE_report(op->reports, RPT_ERROR, "No Contour guide with controllers on the active object");
      return OPERATOR_CANCELLED;
    }
    LISTBASE_FOREACH (ModifierData *, md, &cmd->object->modifiers) {
      if (md->type != eModifierType_Hook) {
        continue;
      }
      Object *emp = ((HookModifierData *)md)->object;
      if (emp != nullptr && envelope_reset_one(emp)) {
        reset_num++;
      }
    }
  }
  else {
    /* Reset the selected controllers, plus the handle children of any reset anchor. */
    BKE_view_layer_synced_ensure(scene, view_layer);
    ListBase *bases = BKE_view_layer_object_bases_get(view_layer);
    blender::Vector<Object *> reset_objects;
    LISTBASE_FOREACH (Base *, base, bases) {
      if ((base->flag & BASE_SELECTED) == 0) {
        continue;
      }
      if (envelope_reset_one(base->object)) {
        reset_objects.append(base->object);
        reset_num++;
      }
    }
    /* Handles are parented to their anchor: pull any whose parent was just reset. */
    LISTBASE_FOREACH (Base *, base, bases) {
      Object *emp = base->object;
      if (emp->parent != nullptr && reset_objects.contains(emp->parent) &&
          !reset_objects.contains(emp) && envelope_reset_one(emp))
      {
        reset_objects.append(emp);
        reset_num++;
      }
    }
    if (reset_num == 0) {
      /* Nothing under the selection is a controller: let native Alt+R (rotation clear) run. */
      return OPERATOR_PASS_THROUGH;
    }
  }

  if (reset_num == 0) {
    return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&scene->id, ID_RECALC_BASE_FLAGS);
  WM_event_add_notifier(C, NC_OBJECT | ND_TRANSFORM, nullptr);
  if (active != nullptr) {
    WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, active);
  }
  return OPERATOR_FINISHED;
}

static wmOperatorStatus greasepencil_contour_reset_invoke(bContext *C,
                                                          wmOperator *op,
                                                          const wmEvent * /*event*/)
{
  /* "All" needs the modifier the panel button points at; "Selected" works straight off selection. */
  if (RNA_enum_get(op->ptr, "mode") == ENVELOPE_RESET_ALL && !edit_modifier_invoke_properties(C, op))
  {
    return OPERATOR_CANCELLED;
  }
  return greasepencil_contour_reset_exec(C, op);
}

void OBJECT_OT_greasepencil_contour_reset(wmOperatorType *ot)
{
  static const EnumPropertyItem mode_items[] = {
      {ENVELOPE_RESET_ALL, "ALL", 0, "All", "Reset every controller of this guide to its rest pose"},
      {ENVELOPE_RESET_SELECTED,
       "SELECTED",
       0,
       "Selected",
       "Reset only the selected controllers (an anchor also resets its handles)"},
      {0, nullptr, 0, nullptr, nullptr},
  };

  ot->name = "Reset Controllers";
  ot->description = "Send the envelope/spine controllers back to their rest pose";
  ot->idname = "OBJECT_OT_greasepencil_contour_reset";

  ot->poll = greasepencil_contour_reset_poll;
  ot->invoke = greasepencil_contour_reset_invoke;
  ot->exec = greasepencil_contour_reset_exec;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
  RNA_def_enum(ot->srna,
               "mode",
               mode_items,
               ENVELOPE_RESET_SELECTED,
               "Mode",
               "Which controllers to send back to rest");
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Toggle Value or Attribute Operator
 *
 * \note This operator basically only exists to provide a better tooltip for the toggle button,
 * since it is stored as an IDProperty. It also stops the button from being highlighted when
 * "use_attribute" is on, which isn't expected.
 * \{ */

static wmOperatorStatus geometry_nodes_input_attribute_toggle_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);

  char modifier_name[MAX_NAME];
  RNA_string_get(op->ptr, "modifier_name", modifier_name);
  NodesModifierData *nmd = (NodesModifierData *)BKE_modifiers_findby_name(ob, modifier_name);
  if (nmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  char input_name[MAX_NAME];
  RNA_string_get(op->ptr, "input_name", input_name);

  IDProperty *use_attribute = IDP_GetPropertyFromGroup(
      nmd->settings.properties, std::string(input_name + std::string("_use_attribute")).c_str());
  if (!use_attribute) {
    return OPERATOR_CANCELLED;
  }

  if (use_attribute->type == IDP_INT) {
    IDP_int_set(use_attribute, !IDP_int_get(use_attribute));
  }
  else if (use_attribute->type == IDP_BOOLEAN) {
    IDP_bool_set(use_attribute, !IDP_bool_get(use_attribute));
  }
  else {
    return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_geometry_nodes_input_attribute_toggle(wmOperatorType *ot)
{
  ot->name = "Input Attribute Toggle";
  ot->description =
      "Switch between an attribute and a single value to define the data for every element";
  ot->idname = "OBJECT_OT_geometry_nodes_input_attribute_toggle";

  ot->exec = geometry_nodes_input_attribute_toggle_exec;
  ot->poll = ED_operator_object_active_editable;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;

  RNA_def_string(ot->srna, "input_name", nullptr, 0, "Input Name", "");
  RNA_def_string(ot->srna, "modifier_name", nullptr, MAX_NAME, "Modifier Name", "");
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Copy and Assign Geometry Node Group operator
 * \{ */

static wmOperatorStatus geometry_node_tree_copy_assign_exec(bContext *C, wmOperator * /*op*/)
{
  Main *bmain = CTX_data_main(C);
  Object *ob = context_active_object(C);
  ModifierData *md = BKE_object_active_modifier(ob);
  if (!(md && md->type == eModifierType_Nodes)) {
    return OPERATOR_CANCELLED;
  }

  NodesModifierData *nmd = (NodesModifierData *)md;
  bNodeTree *tree = nmd->node_group;
  if (tree == nullptr) {
    return OPERATOR_CANCELLED;
  }

  bNodeTree *new_tree = (bNodeTree *)BKE_id_copy_ex(
      bmain, &tree->id, nullptr, LIB_ID_COPY_ACTIONS | LIB_ID_COPY_DEFAULT);

  nmd->flag &= ~NODES_MODIFIER_HIDE_DATABLOCK_SELECTOR;

  if (new_tree == nullptr) {
    return OPERATOR_CANCELLED;
  }

  nmd->node_group = new_tree;
  id_us_min(&tree->id);

  BKE_main_ensure_invariants(*bmain);
  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY);
  DEG_relations_tag_update(bmain);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_geometry_node_tree_copy_assign(wmOperatorType *ot)
{
  ot->name = "New Geometry Node Group";
  ot->description =
      "Duplicate the active geometry node group and assign it to the active modifier";
  ot->idname = "OBJECT_OT_geometry_node_tree_copy_assign";

  ot->exec = geometry_node_tree_copy_assign_exec;
  ot->poll = ED_operator_object_active;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Dash Modifier
 * \{ */

static bool dash_modifier_segment_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_GreasePencilDashModifierData, 0, false, false);
}

static wmOperatorStatus dash_modifier_segment_add_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  auto *dmd = reinterpret_cast<GreasePencilDashModifierData *>(
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilDash));

  if (dmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  GreasePencilDashModifierSegment *new_segments =
      MEM_malloc_arrayN<GreasePencilDashModifierSegment>(dmd->segments_num + 1, __func__);

  const int new_active_index = std::clamp(dmd->segment_active_index + 1, 0, dmd->segments_num);
  if (dmd->segments_num != 0) {
    /* Copy the segments before the new segment. */
    memcpy(new_segments,
           dmd->segments_array,
           sizeof(GreasePencilDashModifierSegment) * new_active_index);
    /* Copy the segments after the new segment. */
    memcpy(new_segments + new_active_index + 1,
           dmd->segments_array + new_active_index,
           sizeof(GreasePencilDashModifierSegment) * (dmd->segments_num - new_active_index));
  }

  /* Create the new segment. */
  GreasePencilDashModifierSegment *ds = &new_segments[new_active_index];
  memcpy(ds,
         DNA_struct_default_get(GreasePencilDashModifierSegment),
         sizeof(GreasePencilDashModifierSegment));
  BLI_uniquename_cb(
      [&](const StringRef name) {
        for (const GreasePencilDashModifierSegment &ds : dmd->segments()) {
          if (STREQ(ds.name, name.data())) {
            return true;
          }
        }
        return false;
      },
      '.',
      ds->name);

  MEM_SAFE_FREE(dmd->segments_array);
  dmd->segments_array = new_segments;
  dmd->segments_num++;
  dmd->segment_active_index = new_active_index;

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY | ID_RECALC_SYNC_TO_EVAL);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus dash_modifier_segment_add_invoke(bContext *C,
                                                         wmOperator *op,
                                                         const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return dash_modifier_segment_add_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_grease_pencil_dash_modifier_segment_add(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Add Segment";
  ot->description = "Add a segment to the dash modifier";
  ot->idname = "OBJECT_OT_grease_pencil_dash_modifier_segment_add";

  /* API callbacks. */
  ot->poll = dash_modifier_segment_poll;
  ot->invoke = dash_modifier_segment_add_invoke;
  ot->exec = dash_modifier_segment_add_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

static void dash_modifier_segment_free(GreasePencilDashModifierSegment * /*ds*/) {}

static wmOperatorStatus dash_modifier_segment_remove_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  auto *dmd = reinterpret_cast<GreasePencilDashModifierData *>(
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilDash));

  if (dmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  if (!dmd->segments().index_range().contains(dmd->segment_active_index)) {
    return OPERATOR_CANCELLED;
  }

  dna::array::remove_index(&dmd->segments_array,
                           &dmd->segments_num,
                           &dmd->segment_active_index,
                           dmd->segment_active_index,
                           dash_modifier_segment_free);

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY | ID_RECALC_SYNC_TO_EVAL);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus dash_modifier_segment_remove_invoke(bContext *C,
                                                            wmOperator *op,
                                                            const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return dash_modifier_segment_remove_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_grease_pencil_dash_modifier_segment_remove(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Remove Dash Segment";
  ot->description = "Remove the active segment from the dash modifier";
  ot->idname = "OBJECT_OT_grease_pencil_dash_modifier_segment_remove";

  /* API callbacks. */
  ot->poll = dash_modifier_segment_poll;
  ot->invoke = dash_modifier_segment_remove_invoke;
  ot->exec = dash_modifier_segment_remove_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);

  RNA_def_int(
      ot->srna, "index", 0, 0, INT_MAX, "Index", "Index of the segment to remove", 0, INT_MAX);
}

enum class DashSegmentMoveDirection {
  Up = -1,
  Down = 1,
};

static wmOperatorStatus dash_modifier_segment_move_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  auto *dmd = reinterpret_cast<GreasePencilDashModifierData *>(
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilDash));

  if (dmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  if (dmd->segments_num < 2) {
    return OPERATOR_CANCELLED;
  }

  const DashSegmentMoveDirection direction = DashSegmentMoveDirection(
      RNA_enum_get(op->ptr, "type"));
  switch (direction) {
    case DashSegmentMoveDirection::Up:
      if (dmd->segment_active_index == 0) {
        return OPERATOR_CANCELLED;
      }

      std::swap(dmd->segments_array[dmd->segment_active_index],
                dmd->segments_array[dmd->segment_active_index - 1]);

      dmd->segment_active_index--;
      break;
    case DashSegmentMoveDirection::Down:
      if (dmd->segment_active_index == dmd->segments_num - 1) {
        return OPERATOR_CANCELLED;
      }

      std::swap(dmd->segments_array[dmd->segment_active_index],
                dmd->segments_array[dmd->segment_active_index + 1]);

      dmd->segment_active_index++;
      break;
    default:
      return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY | ID_RECALC_SYNC_TO_EVAL);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus dash_modifier_segment_move_invoke(bContext *C,
                                                          wmOperator *op,
                                                          const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return dash_modifier_segment_move_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_grease_pencil_dash_modifier_segment_move(wmOperatorType *ot)
{
  static const EnumPropertyItem segment_move[] = {
      {int(DashSegmentMoveDirection::Up), "UP", 0, "Up", ""},
      {int(DashSegmentMoveDirection::Down), "DOWN", 0, "Down", ""},
      {0, nullptr, 0, nullptr, nullptr},
  };

  /* identifiers */
  ot->name = "Move Dash Segment";
  ot->description = "Move the active dash segment up or down";
  ot->idname = "OBJECT_OT_grease_pencil_dash_modifier_segment_move";

  /* API callbacks. */
  ot->poll = dash_modifier_segment_poll;
  ot->invoke = dash_modifier_segment_move_invoke;
  ot->exec = dash_modifier_segment_move_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);

  ot->prop = RNA_def_enum(ot->srna, "type", segment_move, 0, "Type", "");
}

/** \} */

/* ------------------------------------------------------------------- */
/** \name Time Modifier
 * \{ */

static bool time_modifier_segment_poll(bContext *C)
{
  return edit_modifier_poll_generic(C, &RNA_GreasePencilTimeModifier, 0, false, false);
}

static wmOperatorStatus time_modifier_segment_add_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  auto *tmd = reinterpret_cast<GreasePencilTimeModifierData *>(
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilTime));

  if (tmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  GreasePencilTimeModifierSegment *new_segments =
      MEM_malloc_arrayN<GreasePencilTimeModifierSegment>(tmd->segments_num + 1, __func__);

  const int new_active_index = std::clamp(tmd->segment_active_index + 1, 0, tmd->segments_num);
  if (tmd->segments_num != 0) {
    /* Copy the segments before the new segment. */
    memcpy(new_segments,
           tmd->segments_array,
           sizeof(GreasePencilTimeModifierSegment) * new_active_index);
    /* Copy the segments after the new segment. */
    memcpy(new_segments + new_active_index + 1,
           tmd->segments_array + new_active_index,
           sizeof(GreasePencilTimeModifierSegment) * (tmd->segments_num - new_active_index));
  }

  /* Create the new segment. */
  GreasePencilTimeModifierSegment *segment = &new_segments[new_active_index];
  memcpy(segment,
         DNA_struct_default_get(GreasePencilTimeModifierSegment),
         sizeof(GreasePencilTimeModifierSegment));
  BLI_uniquename_cb(
      [&](const StringRef name) {
        for (const GreasePencilTimeModifierSegment &segment : tmd->segments()) {
          if (STREQ(segment.name, name.data())) {
            return true;
          }
        }
        return false;
      },
      '.',
      segment->name);

  MEM_SAFE_FREE(tmd->segments_array);
  tmd->segments_array = new_segments;
  tmd->segments_num++;
  tmd->segment_active_index++;

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY | ID_RECALC_SYNC_TO_EVAL);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus time_modifier_segment_add_invoke(bContext *C,
                                                         wmOperator *op,
                                                         const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return time_modifier_segment_add_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_grease_pencil_time_modifier_segment_add(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Add Segment";
  ot->description = "Add a segment to the time modifier";
  ot->idname = "OBJECT_OT_grease_pencil_time_modifier_segment_add";

  /* API callbacks. */
  ot->poll = time_modifier_segment_poll;
  ot->invoke = time_modifier_segment_add_invoke;
  ot->exec = time_modifier_segment_add_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);
}

static void time_modifier_segment_free(GreasePencilTimeModifierSegment * /*ds*/) {}

static wmOperatorStatus time_modifier_segment_remove_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  auto *tmd = reinterpret_cast<GreasePencilTimeModifierData *>(
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilTime));

  if (tmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  if (!tmd->segments().index_range().contains(tmd->segment_active_index)) {
    return OPERATOR_CANCELLED;
  }

  dna::array::remove_index(&tmd->segments_array,
                           &tmd->segments_num,
                           &tmd->segment_active_index,
                           tmd->segment_active_index,
                           time_modifier_segment_free);

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY | ID_RECALC_SYNC_TO_EVAL);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus time_modifier_segment_remove_invoke(bContext *C,
                                                            wmOperator *op,
                                                            const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return time_modifier_segment_remove_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_grease_pencil_time_modifier_segment_remove(wmOperatorType *ot)
{
  /* identifiers */
  ot->name = "Remove Segment";
  ot->description = "Remove the active segment from the time modifier";
  ot->idname = "OBJECT_OT_grease_pencil_time_modifier_segment_remove";

  /* API callbacks. */
  ot->poll = time_modifier_segment_poll;
  ot->invoke = time_modifier_segment_remove_invoke;
  ot->exec = time_modifier_segment_remove_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);

  RNA_def_int(
      ot->srna, "index", 0, 0, INT_MAX, "Index", "Index of the segment to remove", 0, INT_MAX);
}

enum class TimeSegmentMoveDirection {
  Up = -1,
  Down = 1,
};

static wmOperatorStatus time_modifier_segment_move_exec(bContext *C, wmOperator *op)
{
  Object *ob = context_active_object(C);
  auto *tmd = reinterpret_cast<GreasePencilTimeModifierData *>(
      edit_modifier_property_get(op, ob, eModifierType_GreasePencilTime));

  if (tmd == nullptr) {
    return OPERATOR_CANCELLED;
  }

  if (tmd->segments_num < 2) {
    return OPERATOR_CANCELLED;
  }

  const TimeSegmentMoveDirection direction = TimeSegmentMoveDirection(
      RNA_enum_get(op->ptr, "type"));
  switch (direction) {
    case TimeSegmentMoveDirection::Up:
      if (tmd->segment_active_index == 0) {
        return OPERATOR_CANCELLED;
      }

      std::swap(tmd->segments_array[tmd->segment_active_index],
                tmd->segments_array[tmd->segment_active_index - 1]);

      tmd->segment_active_index--;
      break;
    case TimeSegmentMoveDirection::Down:
      if (tmd->segment_active_index == tmd->segments_num - 1) {
        return OPERATOR_CANCELLED;
      }

      std::swap(tmd->segments_array[tmd->segment_active_index],
                tmd->segments_array[tmd->segment_active_index + 1]);

      tmd->segment_active_index++;
      break;
    default:
      return OPERATOR_CANCELLED;
  }

  DEG_id_tag_update(&ob->id, ID_RECALC_GEOMETRY | ID_RECALC_SYNC_TO_EVAL);
  WM_event_add_notifier(C, NC_OBJECT | ND_MODIFIER, ob);

  return OPERATOR_FINISHED;
}

static wmOperatorStatus time_modifier_segment_move_invoke(bContext *C,
                                                          wmOperator *op,
                                                          const wmEvent * /*event*/)
{
  if (edit_modifier_invoke_properties(C, op)) {
    return time_modifier_segment_move_exec(C, op);
  }
  return OPERATOR_CANCELLED;
}

void OBJECT_OT_grease_pencil_time_modifier_segment_move(wmOperatorType *ot)
{
  static const EnumPropertyItem segment_move[] = {
      {int(TimeSegmentMoveDirection::Up), "UP", 0, "Up", ""},
      {int(TimeSegmentMoveDirection::Down), "DOWN", 0, "Down", ""},
      {0, nullptr, 0, nullptr, nullptr},
  };

  /* identifiers */
  ot->name = "Move Segment";
  ot->description = "Move the active time segment up or down";
  ot->idname = "OBJECT_OT_grease_pencil_time_modifier_segment_move";

  /* API callbacks. */
  ot->poll = time_modifier_segment_poll;
  ot->invoke = time_modifier_segment_move_invoke;
  ot->exec = time_modifier_segment_move_exec;

  /* flags */
  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO | OPTYPE_INTERNAL;
  edit_modifier_properties(ot);

  ot->prop = RNA_def_enum(ot->srna, "type", segment_move, 0, "Type", "");
}

/** \} */

}  // namespace blender::ed::object
