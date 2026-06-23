/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup modifiers
 *
 * Contour (envelope) deformer for Grease Pencil, Toon Boom style.
 *
 * A "cage" object provides a ring of contour points around the drawing. The cage can be either a
 * MESH (its vertices, in index order, are the contour) or a legacy BEZIER CURVE (its first cyclic
 * Bezier spline is tessellated into a closed polygon, so anchors + handles drive the contour like
 * a Toon Boom envelope). Each stroke point is bound to that polygon with 2D Mean Value Coordinates
 * (Hormann & Floater 2006): a normalized, partition-of-unity weighting against every cage vertex.
 * Moving the cage (armature, hooks, drivers on the Bezier handles, ...) deforms the art as
 * `p' = sum_i w_i * v'_i`.
 *
 * The cage's REST shape is the cage object's original (un-evaluated) geometry; the DEFORMED shape
 * is its evaluated geometry (after the cage's own modifier stack / drivers). Because MVC
 * reproduces the rest point exactly when the cage is at rest, no bind data needs to be stored. The
 * rest and deformed contours always have the same point count (same vertex order for a mesh; same
 * spline topology and resolution for a curve), so they correspond index-for-index.
 *
 * NOTE: weights are recomputed every evaluation (no caching yet) and influence is global MVC (no
 * localized zone of influence yet). These are the planned follow-ups.
 */

#include <algorithm>

#include "BLI_index_mask.hh"
#include "BLI_listbase.h"
#include "BLI_math_matrix.hh"
#include "BLI_math_vector.hh"
#include "BLI_string_ref.hh"
#include "BLI_vector.hh"

#include "BLT_translation.hh"

#include "MEM_guardedalloc.h"

#include "BLO_read_write.hh"

#include "DNA_curve_types.h"
#include "DNA_defaults.h"
#include "DNA_mesh_types.h"
#include "DNA_modifier_types.h"
#include "DNA_screen_types.h"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "BKE_curve.hh"
#include "BKE_curves.hh"
#include "BKE_geometry_set.hh"
#include "BKE_grease_pencil.hh"
#include "BKE_lib_query.hh"
#include "BKE_mesh.hh"
#include "BKE_modifier.hh"
#include "BKE_object.hh"
#include "BKE_object_types.hh"

#include "DEG_depsgraph_query.hh"

#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "MOD_grease_pencil_contour.hh"
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
  if (cmd->bind_co != nullptr) {
    tcmd->bind_co = static_cast<float (*)[3]>(MEM_dupallocN(cmd->bind_co));
  }
}

static void free_data(ModifierData *md)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);
  modifier::greasepencil::free_influence_data(&cmd->influence);
  MEM_SAFE_FREE(cmd->bind_co);
}

static bool is_disabled(const Scene * /*scene*/, ModifierData *md, bool /*use_render_params*/)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);
  /* Nuclear: layer-cage mode needs no external object; its validity is checked at eval time. */
  if (cmd->cage_layer[0] != '\0') {
    return false;
  }
  if (cmd->object == nullptr) {
    return true;
  }
  return (cmd->object->type != OB_MESH) && (cmd->object->type != OB_CURVES_LEGACY);
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
  if (cmd->bind_co != nullptr) {
    BLO_write_float3_array(writer, cmd->bind_verts_num, (const float *)cmd->bind_co);
  }
}

static void blend_read(BlendDataReader *reader, ModifierData *md)
{
  auto *cmd = reinterpret_cast<GreasePencilContourModifierData *>(md);
  modifier::greasepencil::read_influence_data(reader, &cmd->influence);
  BLO_read_float3_array(reader, cmd->bind_verts_num, (float **)&cmd->bind_co);
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

/**
 * Tessellate the first cyclic Bezier spline of a legacy curve into a closed polygon.
 *
 * Each segment (including the wrap-around from the last anchor back to the first) is sampled with
 * the spline's own preview resolution `resolu`; the end of each segment is left to the next
 * segment's start, so the result is a non-duplicated ring of `pntsu * resolu` points in
 * curve-local space. Returns false if no usable cyclic Bezier spline is found.
 */
static bool tessellate_bezier_cage(const ListBase &nurbs, Vector<float3> &out)
{
  LISTBASE_FOREACH (const Nurb *, nu, &nurbs) {
    if (nu->type != CU_BEZIER || nu->bezt == nullptr || nu->pntsu < 2) {
      continue;
    }
    if ((nu->flagu & CU_NURB_CYCLIC) == 0) {
      /* The contour must be a closed loop. */
      continue;
    }
    const int n = nu->pntsu;
    const int resolu = std::max<int>(nu->resolu, 1);
    out.reserve(n * resolu);
    for (const int i : IndexRange(n)) {
      const BezTriple &b0 = nu->bezt[i];
      const BezTriple &b1 = nu->bezt[(i + 1) % n];
      /* Cubic Bezier control points: knot, right handle, next left handle, next knot. */
      const float3 p0(b0.vec[1]);
      const float3 p1(b0.vec[2]);
      const float3 p2(b1.vec[0]);
      const float3 p3(b1.vec[1]);
      for (const int s : IndexRange(resolu)) {
        const float t = float(s) / float(resolu);
        const float mt = 1.0f - t;
        out.append(mt * mt * mt * p0 + 3.0f * mt * mt * t * p1 + 3.0f * mt * t * t * p2 +
                   t * t * t * p3);
      }
    }
    return out.size() >= 3;
  }
  return false;
}

}  // namespace blender

namespace blender::modifier::greasepencil {

bool contour_sample_cage(const Object &cage, const bool deformed, Vector<float3> &r_contour)
{
  r_contour.clear();
  if (cage.type == OB_MESH) {
    const Mesh *mesh = deformed ? BKE_modifier_get_evaluated_mesh_from_evaluated_object(
                                      &const_cast<Object &>(cage)) :
                                  static_cast<const Mesh *>(cage.data);
    if (mesh == nullptr) {
      return false;
    }
    const Span<float3> positions = mesh->vert_positions();
    r_contour.reserve(positions.size());
    for (const float3 &v : positions) {
      r_contour.append(v);
    }
    return r_contour.size() >= 3;
  }
  if (cage.type == OB_CURVES_LEGACY) {
    const Curve *cu = static_cast<const Curve *>(cage.data);
    const ListBase *nurbs = &cu->nurb;
    if (deformed && cage.runtime != nullptr && cage.runtime->curve_cache != nullptr &&
        !BLI_listbase_is_empty(&cage.runtime->curve_cache->deformed_nurbs))
    {
      nurbs = &cage.runtime->curve_cache->deformed_nurbs;
    }
    return tessellate_bezier_cage(*nurbs, r_contour);
  }
  return false;
}

bool contour_sample_gp_layer(const GreasePencil &gp,
                             const StringRef layer_name,
                             const int frame,
                             Vector<float3> &r_contour)
{
  using namespace blender::bke::greasepencil;
  r_contour.clear();
  if (layer_name.is_empty()) {
    return false;
  }
  const TreeNode *node = gp.find_node_by_name(layer_name);
  if (node == nullptr || !node->is_layer()) {
    return false;
  }
  const Drawing *drawing = gp.get_drawing_at(node->as_layer(), frame);
  if (drawing == nullptr) {
    return false;
  }
  const bke::CurvesGeometry &curves = drawing->strokes();
  if (curves.curves_num() == 0) {
    return false;
  }
  /* The cage is the layer's FIRST stroke, in Grease Pencil object-local space. Sample the EVALUATED
   * curve (tessellated), not the control points, so a Bezier cage follows its handles: reshaping the
   * stroke with Bezier handles changes the contour and therefore the deform. For a poly stroke the
   * evaluated points equal the control points, so this also covers ordinary strokes. */
  const OffsetIndices<int> eval_by_curve = curves.evaluated_points_by_curve();
  const Span<float3> eval_positions = curves.evaluated_positions();
  const IndexRange first = eval_by_curve[0];
  r_contour.reserve(first.size());
  for (const int p : first) {
    r_contour.append(eval_positions[p]);
  }
  return r_contour.size() >= 3;
}

}  // namespace blender::modifier::greasepencil

namespace blender {

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

  if (!geometry_set->has_grease_pencil()) {
    return;
  }

  /* Nuclear: two cage sources. Layer-cage (cmd->cage_layer set) takes the first stroke of a layer
   * of THIS object as the contour; otherwise the external cmd->object (mesh / Bezier curve). */
  const bool use_layer_cage = cmd->cage_layer[0] != '\0';
  if (!use_layer_cage && cmd->object == nullptr) {
    return;
  }

  GreasePencil &grease_pencil = *geometry_set->get_grease_pencil_for_write();
  const int current_frame = grease_pencil.runtime->eval_frame;

  const bool bound = (cmd->flag & MOD_GREASE_PENCIL_CONTOUR_BOUND) && cmd->bind_co != nullptr &&
                     cmd->bind_verts_num >= 3;

  Vector<float3> def_curve;
  Vector<float3> rest_curve;
  Span<float3> def_pos;
  Span<float3> rest_pos;
  float4x4 gp_to_cage;
  float4x4 cage_to_gp;
  int cage_layer_index = -1;

  if (use_layer_cage) {
    /* Deformed cage = the cage layer's first stroke as it currently is (after the artist's edits /
     * earlier modifiers). Rest = the bind snapshot (binding is required: there is no separate rest
     * object). Cage and art share the Grease Pencil object, so the MVC space is the GP local space
     * and no transform is needed. */
    if (!modifier::greasepencil::contour_sample_gp_layer(
            grease_pencil, cmd->cage_layer, current_frame, def_curve))
    {
      return;
    }
    def_pos = def_curve;
    if (!bound) {
      /* No rest snapshot yet: nothing to deform from (the panel prompts the artist to Bind). */
      return;
    }
    rest_pos = Span<float3>(reinterpret_cast<const float3 *>(cmd->bind_co), cmd->bind_verts_num);
    gp_to_cage = float4x4::identity();
    cage_to_gp = float4x4::identity();

    const Span<const bke::greasepencil::Layer *> layers = grease_pencil.layers();
    for (const int i : layers.index_range()) {
      if (layers[i]->name() == StringRef(cmd->cage_layer)) {
        cage_layer_index = i;
        break;
      }
    }
  }
  else {
    /* Deformed cage = evaluated geometry (after the cage's own modifier stack / direct edits). */
    const Object *cage_orig = DEG_get_original(cmd->object);
    Object *cage_eval = DEG_get_evaluated(ctx->depsgraph, cmd->object);
    if (cage_orig == nullptr || cage_eval == nullptr) {
      return;
    }
    if (!modifier::greasepencil::contour_sample_cage(*cage_eval, true, def_curve)) {
      return;
    }
    def_pos = def_curve;

    /* Rest cage: when bound, the contour snapshot stored at bind time (so editing the cage directly
     * deforms the art); otherwise the cage's live original geometry. */
    if (bound) {
      rest_pos = Span<float3>(reinterpret_cast<const float3 *>(cmd->bind_co), cmd->bind_verts_num);
    }
    else {
      if (!modifier::greasepencil::contour_sample_cage(*cage_orig, false, rest_curve)) {
        return;
      }
      rest_pos = rest_curve;
    }

    /* MVC runs in the cage object's local space; map GP points in and out of it. */
    const float4x4 gp_to_world = ctx->object->object_to_world();
    const float4x4 world_to_gp = ctx->object->world_to_object();
    const float4x4 cage_to_world = cage_eval->object_to_world();
    const float4x4 world_to_cage = cage_eval->world_to_object();
    gp_to_cage = world_to_cage * gp_to_world;
    cage_to_gp = world_to_gp * cage_to_world;
  }

  if (rest_pos.size() != def_pos.size()) {
    return;
  }

  const int cage_num = rest_pos.size();
  if (cage_num < 3) {
    return;
  }

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

  IndexMaskMemory mask_memory;
  IndexMask layer_mask = modifier::greasepencil::get_filtered_layer_mask(
      grease_pencil, cmd->influence, mask_memory);
  /* The cage layer is a deform guide: never deform it with itself. */
  if (use_layer_cage && cage_layer_index >= 0) {
    Vector<int64_t> keep;
    layer_mask.foreach_index([&](const int64_t i) {
      if (i != int64_t(cage_layer_index)) {
        keep.append(i);
      }
    });
    layer_mask = IndexMask::from_indices<int64_t>(keep.as_span(), mask_memory);
  }
  const Vector<bke::greasepencil::Drawing *> drawings =
      modifier::greasepencil::get_drawings_for_write(grease_pencil, layer_mask, current_frame);

  threading::parallel_for_each(drawings, [&](bke::greasepencil::Drawing *drawing) {
    deform_drawing(
        *cmd, *ctx->object, *drawing, cage2_rest, cage2_def, au, av, gp_to_cage, cage_to_gp);
  });
}

static void panel_draw(const bContext *C, Panel *panel)
{
  uiLayout *layout = panel->layout;

  PointerRNA ob_ptr;
  PointerRNA *ptr = modifier_panel_get_property_pointers(panel, &ob_ptr);
  const auto *cmd = static_cast<const GreasePencilContourModifierData *>(ptr->data);

  layout->use_property_split_set(true);

  const bool use_layer_cage = cmd->cage_layer[0] != '\0';

  /* Nuclear: primary cage source = a layer of THIS Grease Pencil object (its first stroke is the
   * contour). Pick the layer here; it acts as a hidden deform guide. */
  PointerRNA gp_ob_ptr = RNA_pointer_create_discrete(ptr->owner_id, &RNA_Object, ptr->owner_id);
  PointerRNA gp_data_ptr = RNA_pointer_get(&gp_ob_ptr, "data");
  layout->prop_search(
      ptr, "cage_layer", &gp_data_ptr, "layers", IFACE_("Cage Layer"), ICON_OUTLINER_DATA_GP_LAYER);

  /* Fall back to an external cage object (mesh / Bezier curve) only when no cage layer is set. */
  if (!use_layer_cage) {
    layout->prop(ptr, "object", UI_ITEM_NONE, IFACE_("Cage Object"), ICON_NONE);
  }
  layout->prop(ptr, "strength", UI_ITEM_R_SLIDER, std::nullopt, ICON_NONE);

  if (use_layer_cage) {
    /* Layer-cage requires a Bind: capture the cage layer's stroke as the rest pose, then edit the
     * stroke to deform the rest of the drawing. */
    const bool bound = (cmd->flag & MOD_GREASE_PENCIL_CONTOUR_BOUND) != 0;
    uiLayout *bind_row = &layout->row(true);
    PointerRNA bind_ptr = bind_row->op(
        "OBJECT_OT_greasepencil_contour_bind", IFACE_("Bind"), ICON_NONE);
    RNA_boolean_set(&bind_ptr, "unbind", false);
    PointerRNA unbind_ptr = bind_row->op(
        "OBJECT_OT_greasepencil_contour_bind", IFACE_("Unbind"), ICON_NONE);
    RNA_boolean_set(&unbind_ptr, "unbind", true);
    if (!bound) {
      layout->label(IFACE_("Bind the cage layer to start deforming"), ICON_INFO);
    }
  }
  else if (cmd->object == nullptr) {
    /* No cage yet: one click traces a Bezier envelope around the drawing, assigns it and binds, so
     * the artist can immediately reshape the contour to deform the art. */
    layout->op("OBJECT_OT_greasepencil_envelope_setup", IFACE_("Create Envelope"), ICON_NONE);
  }
  else {
    /* Bind / Unbind the rest contour: once bound, editing the cage points deforms from the bound
     * rest pose (so a hand-shaped Bezier envelope works without any rig on the cage). */
    uiLayout *bind_row = &layout->row(true);
    PointerRNA bind_ptr = bind_row->op(
        "OBJECT_OT_greasepencil_contour_bind", IFACE_("Bind"), ICON_NONE);
    RNA_boolean_set(&bind_ptr, "unbind", false);
    PointerRNA unbind_ptr = bind_row->op(
        "OBJECT_OT_greasepencil_contour_bind", IFACE_("Unbind"), ICON_NONE);
    RNA_boolean_set(&unbind_ptr, "unbind", true);
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
