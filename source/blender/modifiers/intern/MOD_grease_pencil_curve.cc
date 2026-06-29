/* SPDX-FileCopyrightText: 2024 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup modifiers
 *
 * Grease Pencil "Curve" deform modifier: deforms strokes along a curve object.
 * The artist creates a bezier curve over the drawing, positions/shapes it, then
 * binds it (see OBJECT_OT_greasepencil_curve_bind): each point stores its rest-pose
 * offset in the curve's local frame, so bending the curve bends the drawing locally
 * (Toon Boom style) while the rest pose stays identical. Until bound the modifier is
 * a pass-through, letting 2D animators bend a drawing without needing an armature.
 */

#include <algorithm>

#include "DNA_defaults.h"
#include "DNA_modifier_types.h"

#include "BLI_array.hh"
#include "BLI_math_matrix.hh"
#include "BLI_math_vector.hh"

#include "BKE_curve.hh"
#include "BKE_curves.hh"
#include "BKE_geometry_set.hh"
#include "BKE_grease_pencil.hh"
#include "BKE_lib_query.hh"
#include "BKE_modifier.hh"

#include "BLO_read_write.hh"

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_build.hh"

#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "BLT_translation.hh"

#include "WM_types.hh"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "MOD_grease_pencil_curve.hh"
#include "MOD_grease_pencil_util.hh"
#include "MOD_ui_common.hh"

namespace blender {

using bke::greasepencil::Drawing;
using bke::greasepencil::Layer;

static void init_data(ModifierData *md)
{
  auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);

  BLI_assert(MEMCMP_STRUCT_AFTER_IS_ZERO(cmd, modifier));

  MEMCPY_STRUCT_AFTER(cmd, DNA_struct_default_get(GreasePencilCurveModifierData), modifier);
  modifier::greasepencil::init_influence_data(&cmd->influence, false);
}

static void copy_data(const ModifierData *md, ModifierData *target, const int flag)
{
  const auto *cmd = reinterpret_cast<const GreasePencilCurveModifierData *>(md);
  auto *tcmd = reinterpret_cast<GreasePencilCurveModifierData *>(target);

  modifier::greasepencil::free_influence_data(&tcmd->influence);

  BKE_modifier_copydata_generic(md, target, flag);
  modifier::greasepencil::copy_influence_data(&cmd->influence, &tcmd->influence, flag);
}

static void free_data(ModifierData *md)
{
  auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);
  modifier::greasepencil::free_influence_data(&cmd->influence);
}

static void foreach_ID_link(ModifierData *md, Object *ob, IDWalkFunc walk, void *user_data)
{
  auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);
  modifier::greasepencil::foreach_influence_ID_link(&cmd->influence, ob, walk, user_data);

  walk(user_data, ob, (ID **)&cmd->object, IDWALK_CB_NOP);
}

static void update_depsgraph(ModifierData *md, const ModifierUpdateDepsgraphContext *ctx)
{
  auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);
  if (cmd->object != nullptr) {
    /* The bound-mode deform samples the evaluated curve path (via BKE_where_on_path), so request
     * the curve's geometry/path eval explicitly otherwise there is nothing to follow. */
    DEG_add_object_relation(
        ctx->node, cmd->object, DEG_OB_COMP_TRANSFORM, "Grease Pencil Curve Modifier");
    DEG_add_object_relation(
        ctx->node, cmd->object, DEG_OB_COMP_GEOMETRY, "Grease Pencil Curve Modifier");
    DEG_add_special_eval_flag(ctx->node, &cmd->object->id, DAG_EVAL_NEED_CURVE_PATH);
  }
  DEG_add_depends_on_transform_relation(ctx->node, "Grease Pencil Curve Modifier");
}

static bool is_disabled(const Scene * /*scene*/, ModifierData *md, bool /*use_render_params*/)
{
  auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);

  /* The object type check guards against a placeholder object (e.g. the library containing the
   * curve being missing). */
  return cmd->object == nullptr || cmd->object->type != OB_CURVES_LEGACY;
}

/* Pre-sampled posed curve, shared by every drawing of this modifier evaluation. The table depends
 * only on the curve object (cmd->object) and the GP object (ctx->object) -- never on per-drawing
 * data -- so it is identical for all drawings and is built once (serially) in modify_geometry_set
 * instead of being rebuilt inside modify_curves for each drawing. Binding stores u = k/(N-1), so
 * rounding back to an index reproduces the exact same frame at rest -> identity is preserved. */
struct CurveSampleTable {
  static constexpr int sample_count = 256;
  Array<float3> pos = Array<float3>(sample_count);
  Array<float3x3> frame = Array<float3x3>(sample_count);
  Array<bool> ok = Array<bool>(sample_count);
};

/* Sample the posed curve once, single-threaded: BKE_where_on_path (called via sample_curve) reads
 * shared curve cache state and must not be called concurrently (doing so crashes). Called once per
 * modifier evaluation, before the per-drawing loop. */
static void build_sample_table(ModifierData *md,
                               const ModifierEvalContext *ctx,
                               CurveSampleTable &table)
{
  const auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);
  /* Same drawing-plane normal (in curve-local space) used when binding, so the planar frame matches
   * and the rest pose stays an identity. */
  const float4x4 gp_to_curve = cmd->object->world_to_object() * ctx->object->object_to_world();
  const float3 plane_normal = math::normalize(float3x3(gp_to_curve) * float3(0.0f, 1.0f, 0.0f));

  for (int k = 0; k < CurveSampleTable::sample_count; k++) {
    const float u = float(k) / float(CurveSampleTable::sample_count - 1);
    table.ok[k] = greasepencil_curve::sample_curve(
        *cmd->object, u, plane_normal, table.pos[k], table.frame[k]);
  }
}

static void modify_curves(ModifierData *md,
                          const ModifierEvalContext *ctx,
                          const CurveSampleTable &table,
                          Drawing &drawing)
{
  const auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);
  modifier::greasepencil::ensure_no_bezier_curves(drawing);
  bke::CurvesGeometry &curves = drawing.strokes_for_write();
  if (curves.points_num() == 0) {
    return;
  }

  IndexMaskMemory mask_memory;
  const IndexMask curves_mask = modifier::greasepencil::get_filtered_stroke_mask(
      ctx->object, curves, cmd->influence, mask_memory);

  const OffsetIndices<int> points_by_curve = curves.points_by_curve();
  MutableSpan<float3> positions = curves.positions_for_write();
  const VArray<float> vgroup_weights = modifier::greasepencil::get_influence_vertex_weights(
      curves, cmd->influence);

  /* Bound mode (see OBJECT_OT_greasepencil_curve_bind): each point stored the arc-length
   * parameter `u` of its nearest point on the rest curve plus its offset in the curve's local
   * frame there. We rebuild `curve(u) + frame(u) * offset` on the (possibly bent) curve, which
   * keeps the rest pose identical and bends each section locally — the 2D / Toon Boom behaviour.
   * Without a binding we fall back to the legacy mesh-style curve deform. */
  const bke::AttributeAccessor attributes = curves.attributes();
  const bke::AttributeReader<float> bind_u = attributes.lookup<float>(
      greasepencil_curve::ATTR_U, bke::AttrDomain::Point);
  const bke::AttributeReader<float3> bind_off = attributes.lookup<float3>(
      greasepencil_curve::ATTR_OFFSET, bke::AttrDomain::Point);
  const bool bound = bind_u && bind_off && bind_u.varray.size() == positions.size();

  if (bound) {
    const VArray<float> u_values = bind_u.varray;
    const VArray<float3> offsets = bind_off.varray;
    const float4x4 curve_to_gp = ctx->object->world_to_object() *
                                 cmd->object->object_to_world();

    /* The posed-curve sample table is shared across drawings and built once in
     * modify_geometry_set(); the parallel loop below only reads it. */
    constexpr int sample_count = CurveSampleTable::sample_count;

    curves_mask.foreach_index(GrainSize(512), [&](const int64_t curve_i) {
      const IndexRange points = points_by_curve[curve_i];
      for (const int64_t point_i : points) {
        const int idx = math::clamp(
            int(math::round(u_values[point_i] * float(sample_count - 1))), 0, sample_count - 1);
        if (!table.ok[idx]) {
          continue;
        }
        const float3 target = math::transform_point(
            curve_to_gp, table.pos[idx] + table.frame[idx] * float3(offsets[point_i]));
        const float factor = cmd->strength * vgroup_weights[point_i];
        positions[point_i] = math::interpolate(positions[point_i], target, factor);
      }
    });
  }
  else {
    /* Unbound: leave the drawing untouched so the artist can freely position and shape the curve
     * over it first. The modifier only starts influencing the drawing once "Bind to Rest Pose"
     * stores the per-point binding (see OBJECT_OT_greasepencil_curve_bind). */
    return;
  }

  drawing.tag_positions_changed();
}

static void modify_geometry_set(ModifierData *md,
                                const ModifierEvalContext *ctx,
                                bke::GeometrySet *geometry_set)
{
  const auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);
  BLI_assert(cmd->object != nullptr && cmd->object->type == OB_CURVES_LEGACY);

  if (!geometry_set->has_grease_pencil()) {
    return;
  }
  GreasePencil &grease_pencil = *geometry_set->get_grease_pencil_for_write();

  IndexMaskMemory mask_memory;
  const IndexMask layer_mask = modifier::greasepencil::get_filtered_layer_mask(
      grease_pencil, cmd->influence, mask_memory);
  const int frame = grease_pencil.runtime->eval_frame;
  const Vector<Drawing *> drawings = modifier::greasepencil::get_drawings_for_write(
      grease_pencil, layer_mask, frame);
  if (drawings.is_empty()) {
    return;
  }
  /* Build the shared posed-curve sample table once (serially) -- it is identical for every drawing
   * (depends only on the curve and GP objects, not per-drawing data) and sampling it touches the
   * shared curve cache via BKE_where_on_path(), which is not safe to call concurrently. */
  CurveSampleTable table;
  build_sample_table(md, ctx, table);
  /* Serial across drawings on purpose: although the table is now prebuilt, keeping the drawing loop
   * serial preserves the original ordering. The per-point reconstruction inside modify_curves() is
   * still parallelised (it only reads the pre-sampled table). */
  for (Drawing *drawing : drawings) {
    modify_curves(md, ctx, table, *drawing);
  }
}

static void panel_draw(const bContext *C, Panel *panel)
{
  uiLayout *layout = panel->layout;

  PointerRNA ob_ptr;
  PointerRNA *ptr = modifier_panel_get_property_pointers(panel, &ob_ptr);
  const auto *cmd = static_cast<const GreasePencilCurveModifierData *>(ptr->data);

  layout->use_property_split_set(true);

  layout->prop(ptr, "object", UI_ITEM_NONE, std::nullopt, ICON_NONE);
  layout->prop(ptr, "strength", UI_ITEM_R_SLIDER, std::nullopt, ICON_NONE);

  if (cmd->object == nullptr) {
    /* No curve yet: one click builds a fitted curve, assigns it and binds, so the artist can
     * start bending immediately instead of setting everything up by hand. */
    layout->op("OBJECT_OT_greasepencil_curve_setup", IFACE_("Create Deform Curve"), ICON_NONE);
  }
  else {
    /* Bind / Unbind to rest pose: lets the curve sit on the drawing and deform from there. */
    uiLayout *bind_row = &layout->row(true);
    PointerRNA bind_ptr = bind_row->op(
        "OBJECT_OT_greasepencil_curve_bind", IFACE_("Bind to Rest Pose"), ICON_NONE);
    RNA_boolean_set(&bind_ptr, "unbind", false);
    PointerRNA unbind_ptr = bind_row->op("OBJECT_OT_greasepencil_curve_bind", IFACE_("Unbind"),
                                         ICON_NONE);
    RNA_boolean_set(&unbind_ptr, "unbind", true);
    /* Reset the curve to its rest shape: all of it, or the points selected on the curve. "Selected"
     * acts on the curve's current point selection (set it in the curve's Edit Mode); the mode values
     * mirror the operator's enum (0 = All, 1 = Selected). */
    uiLayout *reset_row = &layout->row(true);
    PointerRNA reset_all = reset_row->op(
        "OBJECT_OT_greasepencil_curve_reset", IFACE_("Reset All"), ICON_LOOP_BACK);
    RNA_enum_set(&reset_all, "mode", 0);
    PointerRNA reset_sel = reset_row->op(
        "OBJECT_OT_greasepencil_curve_reset", IFACE_("Reset Selected"), ICON_LOOP_BACK);
    RNA_enum_set(&reset_sel, "mode", 1);
  }

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
  modifier_panel_register(region_type, eModifierType_GreasePencilCurve, panel_draw);
}

static void blend_write(BlendWriter *writer, const ID * /*id_owner*/, const ModifierData *md)
{
  const auto *cmd = reinterpret_cast<const GreasePencilCurveModifierData *>(md);

  BLO_write_struct(writer, GreasePencilCurveModifierData, cmd);
  modifier::greasepencil::write_influence_data(writer, &cmd->influence);
}

static void blend_read(BlendDataReader *reader, ModifierData *md)
{
  auto *cmd = reinterpret_cast<GreasePencilCurveModifierData *>(md);

  modifier::greasepencil::read_influence_data(reader, &cmd->influence);
}

}  // namespace blender

ModifierTypeInfo modifierType_GreasePencilCurve = {
    /*idname*/ "GreasePencilCurve",
    /*name*/ N_("Curve"),
    /*struct_name*/ "GreasePencilCurveModifierData",
    /*struct_size*/ sizeof(GreasePencilCurveModifierData),
    /*srna*/ &RNA_GreasePencilCurveModifier,
    /*type*/ ModifierTypeType::OnlyDeform,
    /*flags*/ eModifierTypeFlag_AcceptsGreasePencil | eModifierTypeFlag_SupportsEditmode |
        eModifierTypeFlag_EnableInEditmode | eModifierTypeFlag_SupportsMapping,
    /*icon*/ ICON_MOD_CURVE,

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
    /*foreach_cache*/ nullptr,
    /*foreach_working_space_color*/ nullptr,
};
