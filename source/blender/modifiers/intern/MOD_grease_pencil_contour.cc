/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup modifiers
 *
 * Contour (envelope) deformer for Grease Pencil, Toon Boom style.
 *
 * A "cage" mesh object provides a ring of contour points around the drawing. Each stroke point is
 * bound to the cage with 2D Mean Value Coordinates (Hormann & Floater 2006): a normalized,
 * partition-of-unity weighting against every cage vertex. Moving the cage (e.g. via an armature on
 * the cage mesh) deforms the art as `p' = sum_i w_i * v'_i`.
 *
 * The cage's REST shape is the cage object's original (un-evaluated) mesh; the DEFORMED shape is
 * its evaluated mesh (after the cage's own modifier stack). Because MVC reproduces the rest point
 * exactly when the cage is at rest, no bind data needs to be stored.
 *
 * NOTE (v1): weights are recomputed every evaluation (no caching yet), the cage is treated as a
 * polygon (no Bezier tessellation yet), and influence is global MVC (no localized zone of
 * influence). These are the planned follow-ups.
 */

#include "BLI_index_mask.hh"
#include "BLI_math_matrix.hh"
#include "BLI_math_vector.hh"

#include "BLT_translation.hh"

#include "BLO_read_write.hh"

#include "DNA_defaults.h"
#include "DNA_mesh_types.h"
#include "DNA_modifier_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "BKE_curves.hh"
#include "BKE_geometry_set.hh"
#include "BKE_grease_pencil.hh"
#include "BKE_lib_query.hh"
#include "BKE_mesh.hh"
#include "BKE_modifier.hh"
#include "BKE_object.hh"

#include "DEG_depsgraph_query.hh"

#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "MOD_grease_pencil_util.hh"
#include "MOD_modifiertypes.hh"
#include "MOD_ui_common.hh"

namespace blender {

static void init_data(ModifierData *md)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);

  BLI_assert(MEMCMP_STRUCT_AFTER_IS_ZERO(cmd, modifier));

  MEMCPY_STRUCT_AFTER(cmd, DNA_struct_default_get(GreasePencilContourModifierData), modifier);
  modifier::greasepencil::init_influence_data(&cmd->influence, false);
}

static void copy_data(const ModifierData *md, ModifierData *target, const int flag)
{
  const auto *cmd = reinterpret_cast<const GreasePencilContourModifierData *>(md);
  auto *tcmd = reinterpret_cast<GreasePencilContourModifierData *>(target);

  BKE_modifier_copydata_generic(md, target, flag);
  modifier::greasepencil::copy_influence_data(&cmd->influence, &tcmd->influence, flag);
}

static void free_data(ModifierData *md)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);
  modifier::greasepencil::free_influence_data(&cmd->influence);
}

static bool is_disabled(const Scene * /*scene*/, ModifierData *md, bool /*use_render_params*/)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);
  return (cmd->object == nullptr) || (cmd->object->type != OB_MESH);
}

static void update_depsgraph(ModifierData *md, const ModifierUpdateDepsgraphContext *ctx)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);
  if (cmd->object != nullptr) {
    DEG_add_object_relation(
        ctx->node, cmd->object, DEG_OB_COMP_TRANSFORM, "Grease Pencil Contour Modifier");
    DEG_add_object_relation(
        ctx->node, cmd->object, DEG_OB_COMP_GEOMETRY, "Grease Pencil Contour Modifier");
  }
  DEG_add_depends_on_transform_relation(ctx->node, "Grease Pencil Contour Modifier");
}

static void foreach_ID_link(ModifierData *md, Object *ob, IDWalkFunc walk, void *user_data)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);
  modifier::greasepencil::foreach_influence_ID_link(&cmd->influence, ob, walk, user_data);
  walk(user_data, ob, (ID **)&cmd->object, IDWALK_CB_NOP);
}

static void blend_write(BlendWriter *writer, const ID * /*id_owner*/, const ModifierData *md)
{
  const auto *cmd = reinterpret_cast<const GreasePencilContourModifierData *>(md);
  BLO_write_struct(writer, GreasePencilContourModifierData, cmd);
  modifier::greasepencil::write_influence_data(writer, &cmd->influence);
}

static void blend_read(BlendDataReader *reader, ModifierData *md)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);
  modifier::greasepencil::read_influence_data(reader, &cmd->influence);
}

/**
 * 2D Mean Value Coordinates deform of a single point.
 *
 * Returns the deformed 2D position: the MVC-weighted average of the deformed cage `def_`, using
 * weights computed against the rest cage `rest`. `s`, `r`, `tanhalf` are caller-provided scratch
 * buffers of size `rest.size()` (reused across points to avoid per-point allocation).
 */
static float2 mvc_deform_point(const float2 &p,
                               const Span<float2> rest,
                               const Span<float2> def_,
                               MutableSpan<float2> s,
                               MutableSpan<float> r,
                               MutableSpan<float> tanhalf)
{
  const int n = rest.size();
  const float eps = 1e-7f;

  for (const int i : IndexRange(n)) {
    s[i] = rest[i] - p;
    r[i] = math::length(s[i]);
    if (r[i] < eps) {
      /* Point coincides with a cage vertex. */
      return def_[i];
    }
  }

  for (const int i : IndexRange(n)) {
    const int j = (i + 1) % n;
    const float cross = s[i].x * s[j].y - s[i].y * s[j].x;
    const float dot = s[i].x * s[j].x + s[i].y * s[j].y;
    if (math::abs(cross) < eps && dot < 0.0f) {
      /* Point lies on the edge (i, j): linear interpolation. */
      const float t = r[i] / (r[i] + r[j]);
      return def_[i] * (1.0f - t) + def_[j] * t;
    }
    tanhalf[i] = (r[i] * r[j] - dot) / (math::abs(cross) < eps ? eps : cross);
  }

  float2 num(0.0f, 0.0f);
  float den = 0.0f;
  for (const int i : IndexRange(n)) {
    const int ip = (i + n - 1) % n;
    const float w = (tanhalf[ip] + tanhalf[i]) / r[i];
    num += def_[i] * w;
    den += w;
  }
  if (math::abs(den) < eps) {
    return p;
  }
  return num / den;
}

static void deform_drawing(const GreasePencilContourModifierData &cmd,
                           const Object &ob,
                           bke::greasepencil::Drawing &drawing,
                           const Span<float2> cage2_rest,
                           const Span<float2> cage2_def,
                           const int au,
                           const int av,
                           const float4x4 &gp_to_cage,
                           const float4x4 &cage_to_gp)
{
  modifier::greasepencil::ensure_no_bezier_curves(drawing);
  bke::CurvesGeometry &curves = drawing.strokes_for_write();
  if (curves.is_empty()) {
    return;
  }

  IndexMaskMemory memory;
  const IndexMask strokes = modifier::greasepencil::get_filtered_stroke_mask(
      &ob, curves, cmd.influence, memory);
  if (strokes.is_empty()) {
    return;
  }

  const VArray<float> input_weights = modifier::greasepencil::get_influence_vertex_weights(
      curves, cmd.influence);

  const float strength = cmd.strength;
  const int cage_num = cage2_rest.size();
  const OffsetIndices<int> points_by_curve = curves.points_by_curve();
  MutableSpan<float3> positions = curves.positions_for_write();

  strokes.foreach_index(blender::GrainSize(64), [&](const int stroke) {
    Array<float2> s(cage_num);
    Array<float> r(cage_num);
    Array<float> tanhalf(cage_num);

    for (const int point : points_by_curve[stroke]) {
      const float weight = input_weights[point];
      if (weight < 0.0f) {
        continue;
      }
      const float3 p_cage = math::transform_point(gp_to_cage, positions[point]);
      const float2 p2(p_cage[au], p_cage[av]);
      const float2 t2 = mvc_deform_point(p2, cage2_rest, cage2_def, s, r, tanhalf);

      float3 target_cage = p_cage;
      target_cage[au] = t2.x;
      target_cage[av] = t2.y;
      const float3 target_gp = math::transform_point(cage_to_gp, target_cage);

      positions[point] = math::interpolate(positions[point], target_gp, strength * weight);
    }
  });

  drawing.tag_positions_changed();
}

static void modify_geometry_set(ModifierData *md,
                                const ModifierEvalContext *ctx,
                                bke::GeometrySet *geometry_set)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);

  if (!geometry_set->has_grease_pencil() || cmd->object == nullptr) {
    return;
  }

  /* Rest cage = original (un-evaluated) mesh; deformed cage = evaluated mesh. */
  const Object *cage_orig = DEG_get_original(cmd->object);
  Object *cage_eval = DEG_get_evaluated(ctx->depsgraph, cmd->object);
  if (cage_orig == nullptr || cage_eval == nullptr || cage_orig->type != OB_MESH) {
    return;
  }
  const Mesh *rest_mesh = static_cast<const Mesh *>(cage_orig->data);
  const Mesh *def_mesh = BKE_modifier_get_evaluated_mesh_from_evaluated_object(cage_eval);
  if (rest_mesh == nullptr || def_mesh == nullptr) {
    return;
  }
  const int cage_num = rest_mesh->verts_num;
  if (cage_num < 3 || def_mesh->verts_num != cage_num) {
    return;
  }

  const Span<float3> rest_pos = rest_mesh->vert_positions();
  const Span<float3> def_pos = def_mesh->vert_positions();

  /* Working plane = the two cage-local axes of largest extent (normal axis is preserved). */
  float3 mn = rest_pos[0];
  float3 mx = rest_pos[0];
  for (const float3 &v : rest_pos) {
    mn = math::min(mn, v);
    mx = math::max(mx, v);
  }
  const float3 ext = mx - mn;
  int an = 0;
  if (ext[1] < ext[an]) {
    an = 1;
  }
  if (ext[2] < ext[an]) {
    an = 2;
  }
  const int au = (an + 1) % 3;
  const int av = (an + 2) % 3;

  Array<float2> cage2_rest(cage_num);
  Array<float2> cage2_def(cage_num);
  for (const int i : IndexRange(cage_num)) {
    cage2_rest[i] = float2(rest_pos[i][au], rest_pos[i][av]);
    cage2_def[i] = float2(def_pos[i][au], def_pos[i][av]);
  }

  /* MVC runs entirely in the cage object's local space; map GP points in and out of it. */
  const float4x4 gp_to_world = ctx->object->object_to_world();
  const float4x4 world_to_gp = ctx->object->world_to_object();
  const float4x4 cage_to_world = cage_eval->object_to_world();
  const float4x4 world_to_cage = cage_eval->world_to_object();
  const float4x4 gp_to_cage = world_to_cage * gp_to_world;
  const float4x4 cage_to_gp = world_to_gp * cage_to_world;

  GreasePencil &grease_pencil = *geometry_set->get_grease_pencil_for_write();
  const int current_frame = grease_pencil.runtime->eval_frame;

  IndexMaskMemory mask_memory;
  const IndexMask layer_mask = modifier::greasepencil::get_filtered_layer_mask(
      grease_pencil, cmd->influence, mask_memory);
  const Vector<bke::greasepencil::Drawing *> drawings =
      modifier::greasepencil::get_drawings_for_write(grease_pencil, layer_mask, current_frame);

  threading::parallel_for_each(drawings, [&](bke::greasepencil::Drawing *drawing) {
    deform_drawing(*cmd, *ctx->object, *drawing, cage2_rest, cage2_def, au, av, gp_to_cage, cage_to_gp);
  });
}

static void panel_draw(const bContext *C, Panel *panel)
{
  uiLayout *layout = panel->layout;

  PointerRNA ob_ptr;
  PointerRNA *ptr = modifier_panel_get_property_pointers(panel, &ob_ptr);

  layout->use_property_split_set(true);

  layout->prop(ptr, "object", UI_ITEM_NONE, IFACE_("Cage"), ICON_NONE);
  layout->prop(ptr, "strength", UI_ITEM_R_SLIDER, std::nullopt, ICON_NONE);

  if (uiLayout *influence_panel = layout->panel_prop(
          C, ptr, "open_influence_panel", IFACE_("Influence")))
  {
    modifier::greasepencil::draw_layer_filter_settings(C, influence_panel, ptr);
    modifier::greasepencil::draw_material_filter_settings(C, influence_panel, ptr);
    modifier::greasepencil::draw_vertex_group_settings(C, influence_panel, ptr);
  }

  modifier_error_message_draw(layout, ptr);
}

static void panel_register(ARegionType *region_type)
{
  modifier_panel_register(region_type, eModifierType_GreasePencilContour, panel_draw);
}

}  // namespace blender

ModifierTypeInfo modifierType_GreasePencilContour = {
    /*idname*/ "GreasePencilContourModifier",
    /*name*/ N_("Contour Deform"),
    /*struct_name*/ "GreasePencilContourModifierData",
    /*struct_size*/ sizeof(GreasePencilContourModifierData),
    /*srna*/ &RNA_GreasePencilContourModifier,
    /*type*/ ModifierTypeType::OnlyDeform,
    /*flags*/
    eModifierTypeFlag_AcceptsGreasePencil | eModifierTypeFlag_SupportsEditmode |
        eModifierTypeFlag_EnableInEditmode | eModifierTypeFlag_SupportsMapping,
    /*icon*/ ICON_MOD_MESHDEFORM,

    /*copy_data*/ blender::copy_data,

    /*deform_verts*/ nullptr,
    /*deform_matrices*/ nullptr,
    /*deform_verts_EM*/ nullptr,
    /*deform_matrices_EM*/ nullptr,
    /*modify_mesh*/ nullptr,
    /*modify_geometry_set*/ blender::modify_geometry_set,

    /*init_data*/ blender::init_data,
    /*required_data_mask*/ nullptr,
    /*free_data*/ blender::free_data,
    /*is_disabled*/ blender::is_disabled,
    /*update_depsgraph*/ blender::update_depsgraph,
    /*depends_on_time*/ nullptr,
    /*depends_on_normals*/ nullptr,
    /*foreach_ID_link*/ blender::foreach_ID_link,
    /*foreach_tex_link*/ nullptr,
    /*free_runtime_data*/ nullptr,
    /*panel_register*/ blender::panel_register,
    /*blend_write*/ blender::blend_write,
    /*blend_read*/ blender::blend_read,
};
