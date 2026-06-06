/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edtransform
 */

#include "ANIM_keyframing.hh"

#include "BKE_context.hh"
#include "BKE_curves_utils.hh"
#include "BKE_layer.hh"
#include "BKE_scene.hh"

#include "BLI_index_mask_expression.hh"
#include "BLI_math_matrix.h"

#include "DEG_depsgraph_query.hh"

#include "ED_curves.hh"
#include "ED_grease_pencil.hh"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "transform.hh"
#include "transform_convert.hh"
#include "transform_snap.hh"

/* -------------------------------------------------------------------- */
/** \name Grease Pencil Transform Creation
 * \{ */

namespace blender::ed::transform::greasepencil {

static void createTransGreasePencilVerts(bContext *C, TransInfo *t)
{
  Depsgraph *depsgraph = CTX_data_depsgraph_pointer(C);
  Scene *scene = CTX_data_scene(C);
  Object *object = CTX_data_active_object(C);
  MutableSpan<TransDataContainer> trans_data_contrainers(t->data_container, t->data_container_len);
  const bool use_proportional_edit = (t->flag & T_PROP_EDIT_ALL) != 0;
  const bool use_connected_only = (t->flag & T_PROP_CONNECTED) != 0;
  const bool use_individual_origins = (t->around == V3D_AROUND_LOCAL_ORIGINS);
  ToolSettings *ts = scene->toolsettings;
  const bool is_scale_thickness = ((t->mode == TFM_CURVE_SHRINKFATTEN) ||
                                   (ts->gp_sculpt.flag & GP_SCULPT_SETT_FLAG_SCALE_THICKNESS));

  int total_number_of_drawings = 0;
  Vector<CurvesTransformData *> all_curves_transform_data;
  /* Count the number layers in all objects. */
  for (const int i : trans_data_contrainers.index_range()) {
    TransDataContainer &tc = trans_data_contrainers[i];
    GreasePencil &grease_pencil = *static_cast<GreasePencil *>(tc.obedit->data);

    CurvesTransformData *curves_transform_data = curves::create_curves_transform_custom_data(
        tc.custom.type);

    curves_transform_data->drawings = ed::greasepencil::retrieve_editable_drawings_with_falloff(
        *scene, grease_pencil);

    if (animrig::is_autokey_on(scene)) {
      for (const int info_i : curves_transform_data->drawings.index_range()) {
        bke::greasepencil::Layer &target_layer = grease_pencil.layer(
            curves_transform_data->drawings[info_i].layer_index);
        const int current_frame = scene->r.cfra;
        std::optional<int> start_frame = target_layer.start_frame_at(current_frame);
        if (start_frame.has_value() && (start_frame.value() != current_frame)) {
          grease_pencil.insert_duplicate_frame(
              target_layer, *target_layer.start_frame_at(current_frame), current_frame, false);
        }
      }
      curves_transform_data->drawings = ed::greasepencil::retrieve_editable_drawings_with_falloff(
          *scene, grease_pencil);
    }

    all_curves_transform_data.append(curves_transform_data);
    total_number_of_drawings += curves_transform_data->drawings.size();
  }

  Array<Vector<IndexMask>> points_to_transform_per_attribute(total_number_of_drawings);
  Array<IndexMask> bezier_curves(total_number_of_drawings);
  int layer_offset = 0;

  /* Count selected elements per layer per object and create TransData structs. */
  for (const int i : trans_data_contrainers.index_range()) {
    TransDataContainer &tc = trans_data_contrainers[i];
    CurvesTransformData &curves_transform_data = *all_curves_transform_data[i];
    tc.data_len = 0;

    const Span<ed::greasepencil::MutableDrawingInfo> drawings =
        curves_transform_data.drawings.as_span();
    curves_transform_data.grease_pencil_falloffs.reinitialize(drawings.size());

    for (ed::greasepencil::MutableDrawingInfo info : drawings) {
      bke::CurvesGeometry &curves = info.drawing.strokes_for_write();
      Span<StringRef> selection_attribute_names = ed::curves::get_curves_selection_attribute_names(
          curves);
      std::array<IndexMask, 3> selection_per_attribute;

      const IndexMask editable_points = ed::greasepencil::retrieve_editable_points(
          *object, info.drawing, info.layer_index, curves_transform_data.memory);
      const IndexMask editable_strokes = ed::greasepencil::retrieve_editable_strokes(
          *object, info.drawing, info.layer_index, curves_transform_data.memory);

      bezier_curves[layer_offset] = bke::curves::indices_for_type(curves.curve_types(),
                                                                  curves.curve_type_counts(),
                                                                  CURVE_TYPE_BEZIER,
                                                                  editable_strokes,
                                                                  curves_transform_data.memory);
      const OffsetIndices<int> points_by_curve = curves.points_by_curve();
      const IndexMask bezier_points = IndexMask::from_ranges(
          points_by_curve, bezier_curves[layer_offset], curves_transform_data.memory);

      for (const int attribute_i : selection_attribute_names.index_range()) {
        const StringRef &selection_name = selection_attribute_names[attribute_i];
        selection_per_attribute[attribute_i] = ed::curves::retrieve_selected_points(
            curves, selection_name, bezier_points, curves_transform_data.memory);

        /* Make sure only editable points are used. */
        selection_per_attribute[attribute_i] = IndexMask::from_intersection(
            selection_per_attribute[attribute_i], editable_points, curves_transform_data.memory);
      }

      /* Alter selection as in legacy curves bezt_select_to_transform_triple_flag(). */
      if (!bezier_points.is_empty()) {
        if (curves::update_handle_types_for_transform(
                t->mode, selection_per_attribute, bezier_points, curves))
        {
          info.drawing.tag_topology_changed();
        }

        index_mask::ExprBuilder builder;
        const index_mask::Expr &selected_bezier_points = builder.intersect(
            {&bezier_points, &selection_per_attribute[0]});

        /* Select bezier handles that must be transformed because the control point is
         * selected. */
        selection_per_attribute[1] = evaluate_expression(
            builder.merge({&selection_per_attribute[1], &selected_bezier_points}),
            curves_transform_data.memory);
        selection_per_attribute[2] = evaluate_expression(
            builder.merge({&selection_per_attribute[2], &selected_bezier_points}),
            curves_transform_data.memory);
      }

      if (use_proportional_edit) {
        const IndexMask editable_bezier_points = IndexMask::from_intersection(
            editable_points, bezier_points, curves_transform_data.memory);
        tc.data_len += editable_points.size() + 2 * editable_bezier_points.size();
        points_to_transform_per_attribute[layer_offset].append(editable_points);

        if (selection_attribute_names.size() > 1) {
          points_to_transform_per_attribute[layer_offset].append(editable_bezier_points);
          points_to_transform_per_attribute[layer_offset].append(editable_bezier_points);
        }
      }
      else {
        for (const int selection_i : selection_attribute_names.index_range()) {
          points_to_transform_per_attribute[layer_offset].append(
              selection_per_attribute[selection_i]);
          tc.data_len += points_to_transform_per_attribute[layer_offset][selection_i].size();
        }
      }

      layer_offset++;
    }

    if (tc.data_len > 0) {
      tc.data = MEM_calloc_arrayN<TransData>(tc.data_len, __func__);
      curves_transform_data.positions.reinitialize(tc.data_len);
    }
    else {
      tc.custom.type.free_cb(t, &tc, &tc.custom.type);
    }
  }

  /* Reuse the variable `layer_offset`. */
  layer_offset = 0;
  IndexMaskMemory memory;

  /* Populate TransData structs. */
  for (const int i : trans_data_contrainers.index_range()) {
    TransDataContainer &tc = trans_data_contrainers[i];
    if (tc.data_len == 0) {
      continue;
    }
    Object *object_eval = DEG_get_evaluated(depsgraph, tc.obedit);
    GreasePencil &grease_pencil = *static_cast<GreasePencil *>(tc.obedit->data);
    Span<const bke::greasepencil::Layer *> layers = grease_pencil.layers();

    CurvesTransformData &transform_data = *static_cast<CurvesTransformData *>(tc.custom.type.data);
    const Span<ed::greasepencil::MutableDrawingInfo> drawings = transform_data.drawings.as_span();

    transform_data.aligned_with_left.reinitialize(drawings.size());
    transform_data.aligned_with_right.reinitialize(drawings.size());

    for (const int drawing : drawings.index_range()) {
      ed::greasepencil::MutableDrawingInfo info = drawings[drawing];
      const bke::greasepencil::Layer &layer = *layers[info.layer_index];
      const float4x4 layer_space_to_world_space = layer.to_world_space(*object_eval);
      bke::CurvesGeometry &curves = info.drawing.strokes_for_write();
      const bke::crazyspace::GeometryDeformation deformation =
          bke::crazyspace::get_evaluated_grease_pencil_drawing_deformation(
              *CTX_data_depsgraph_pointer(C), *object, info.drawing);

      std::optional<MutableSpan<float>> value_attribute;
      if (t->mode == TFM_GPENCIL_OPACITY) {
        MutableSpan<float> opacities = info.drawing.opacities_for_write();
        value_attribute = opacities;
      }
      else if (is_scale_thickness) {
        MutableSpan<float> radii = info.drawing.radii_for_write();
        value_attribute = radii;
      }

      const IndexMask affected_strokes = use_proportional_edit || use_individual_origins ?
                                             ed::greasepencil::retrieve_editable_strokes(
                                                 *object, info.drawing, info.layer_index, memory) :
                                             IndexMask();

      CurvesTransformData &curves_transform_data = *static_cast<CurvesTransformData *>(
          tc.custom.type.data);
      curves_transform_data.grease_pencil_falloffs[drawing] = info.multi_frame_falloff;
      float &drawing_falloff = curves_transform_data.grease_pencil_falloffs[drawing];
      curves::curve_populate_trans_data_structs(*t,
                                                tc,
                                                curves,
                                                layer_space_to_world_space,
                                                deformation,
                                                value_attribute,
                                                points_to_transform_per_attribute[layer_offset],
                                                affected_strokes,
                                                use_connected_only,
                                                bezier_curves[layer_offset],
                                                &drawing_falloff);
      curves::create_aligned_handles_masks(
          curves, points_to_transform_per_attribute[layer_offset], drawing, tc.custom.type);

      layer_offset++;
    }
  }
}

static void recalcData_grease_pencil(TransInfo *t)
{
  if (t->state != TRANS_CANCEL) {
    transform_snap_project_individual_apply(t);
  }

  const Span<TransDataContainer> trans_data_contrainers(t->data_container, t->data_container_len);
  for (const TransDataContainer &tc : trans_data_contrainers) {
    GreasePencil &grease_pencil = *static_cast<GreasePencil *>(tc.obedit->data);
    const CurvesTransformData &transform_data = *static_cast<CurvesTransformData *>(
        tc.custom.type.data);

    const Vector<ed::greasepencil::MutableDrawingInfo> drawings = transform_data.drawings;

    int layer_i = 0;
    for (const int64_t i : drawings.index_range()) {
      ed::greasepencil::MutableDrawingInfo info = drawings[i];
      bke::CurvesGeometry &curves = info.drawing.strokes_for_write();

      if (t->mode == TFM_CURVE_SHRINKFATTEN) {
        curves.tag_radii_changed();
      }
      else if (t->mode == TFM_TILT) {
        curves.tag_normals_changed();
      }
      else {
        const Vector<MutableSpan<float3>> positions_per_selection_attr =
            ed::curves::get_curves_positions_for_write(curves);
        for (MutableSpan<float3> positions : positions_per_selection_attr) {
          curves::copy_positions_from_curves_transform_custom_data(
              tc.custom.type, layer_i++, positions);
        }
        curves.tag_positions_changed();
        curves.calculate_bezier_auto_handles();
        info.drawing.tag_positions_changed();
        curves::calculate_aligned_handles(tc.custom.type, curves, i);
      }
    }

    DEG_id_tag_update(&grease_pencil.id, ID_RECALC_GEOMETRY);
  }
}

/** \} */

TransConvertTypeInfo TransConvertType_GreasePencil = {
    /*flags*/ (T_EDIT | T_POINTS),
    /*create_trans_data*/ createTransGreasePencilVerts,
    /*recalc_data*/ recalcData_grease_pencil,
    /*special_aftertrans_update*/ nullptr,
};

/* -------------------------------------------------------------------- */
/** \name Grease Pencil Peg (object-mode transform of the active peg layer-group)
 * \{ */

static void createTransGreasePencilPeg(bContext * /*C*/, TransInfo *t)
{
  using namespace blender::bke::greasepencil;

  BKE_view_layer_synced_ensure(t->scene, t->view_layer);
  Object *object = BKE_view_layer_active_object_get(t->view_layer);
  if (object == nullptr || object->type != OB_GREASE_PENCIL) {
    return;
  }
  GreasePencil &grease_pencil = *static_cast<GreasePencil *>(object->data);
  TreeNode *active = grease_pencil.get_active_node();
  if (active == nullptr || !active->is_group()) {
    return;
  }
  LayerGroup &group = active->as_group();

  BLI_assert(t->data_container_len == 1);
  TransDataContainer *tc = t->data_container;
  tc->data_len = 1;
  TransData *td = tc->data = MEM_callocN<TransData>(__func__);
  TransDataExtension *td_ext = tc->data_ext = MEM_callocN<TransDataExtension>(__func__);

  /* The peg's local transform lives in the frame `object_to_world * ancestor pegs`. */
  const float4x4 peg_to_world = object->object_to_world() * group.to_object_space();
  const float4x4 peg_local = group.local_transform();

  td->flag = TD_SELECTED;
  td->extra = object;

  td->loc = group.translation;
  copy_v3_v3(td->iloc, group.translation);

  td_ext->rot = group.rotation;
  td_ext->rotAxis = nullptr;
  td_ext->rotAngle = nullptr;
  td_ext->quat = nullptr;
  copy_v3_v3(td_ext->irot, group.rotation);
  zero_v3(td_ext->drot);
  td_ext->rotOrder = ROT_MODE_EUL;

  td_ext->scale = group.scale;
  copy_v3_v3(td_ext->iscale, group.scale);
  copy_v3_fl(td_ext->dscale, 1.0f);

  copy_v3_v3(td->center, peg_to_world.location());

  /* Orientation axes from the peg's world transform. */
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

static void recalcData_grease_pencil_peg(TransInfo *t)
{
  const TransDataContainer *tc = t->data_container;
  if (tc->data_len == 0 || tc->data == nullptr) {
    return;
  }
  Object *object = static_cast<Object *>(tc->data[0].extra);
  if (object == nullptr) {
    return;
  }
  /* The peg transform feeds into the layer-to-object-space evaluation, so the drawings need to be
   * re-evaluated for the change to show up. */
  DEG_id_tag_update(static_cast<ID *>(object->data), ID_RECALC_GEOMETRY);
}

static void special_aftertrans_update_grease_pencil_peg(bContext *C, TransInfo *t)
{
  using namespace blender::bke::greasepencil;
  if (t->state == TRANS_CANCEL) {
    return;
  }
  if (!animrig::is_autokey_on(t->scene)) {
    return;
  }
  const TransDataContainer *tc = t->data_container;
  if (tc == nullptr || tc->data_len == 0 || tc->data == nullptr) {
    return;
  }
  Object *object = static_cast<Object *>(tc->data[0].extra);
  if (object == nullptr) {
    return;
  }
  GreasePencil &grease_pencil = *static_cast<GreasePencil *>(object->data);
  if (!animrig::autokeyframe_cfra_can_key(t->scene, &grease_pencil.id)) {
    return;
  }
  TreeNode *active = grease_pencil.get_active_node();
  if (active == nullptr || !active->is_group()) {
    return;
  }

  PointerRNA group_ptr = RNA_pointer_create_discrete(
      &grease_pencil.id, &RNA_GreasePencilLayerGroup, &active->as_group());
  const float cfra = BKE_scene_frame_get(t->scene);
  /* Key the whole peg pose (translation, rotation and scale) so cut-out poses have no gaps. */
  for (const char *prop_name : {"translation", "rotation", "scale"}) {
    if (PropertyRNA *prop = RNA_struct_find_property(&group_ptr, prop_name)) {
      animrig::autokeyframe_property(C, t->scene, &group_ptr, prop, -1, cfra, false);
    }
  }
}

/** \} */

TransConvertTypeInfo TransConvertType_GreasePencilPeg = {
    /*flags*/ 0,
    /*create_trans_data*/ createTransGreasePencilPeg,
    /*recalc_data*/ recalcData_grease_pencil_peg,
    /*special_aftertrans_update*/ special_aftertrans_update_grease_pencil_peg,
};

}  // namespace blender::ed::transform::greasepencil
