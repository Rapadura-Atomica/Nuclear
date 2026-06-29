/* SPDX-FileCopyrightText: 2024 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup modifiers
 *
 * Nuclear Grease Pencil "Cutter" / cross-object mask modifier (Toon Boom style).
 *
 * In the peg cut-out model every body part is a separate Grease Pencil object, so the native
 * Grease Pencil layer mask (which is strictly same-object) can no longer clip e.g. a pupil to the
 * silhouette of a separate eye object. This modifier restores that: it lives on the MASKED object
 * (the pupil) and references a matte object (the eye). At evaluation time it injects the matte's
 * evaluated strokes as an extra, opacity-0 (so invisible but still rasterized into the mask
 * buffer) layer inside the pupil's evaluated Grease Pencil, then wires a native
 * #GreasePencilLayerMask on the filtered layers pointing at that injected layer. The existing
 * same-object GPU mask pipeline then produces the alpha matte — no draw-engine changes.
 *
 * Because the matte object's evaluated world transform (including its Follow Peg constraint) is
 * baked into the injected geometry, the clip follows the matte's peg automatically. The matte
 * object itself keeps rendering normally; the modifier only borrows its silhouette.
 */

#include <cstddef>
#include <string>

#include "MEM_guardedalloc.h"

#include "DNA_defaults.h"
#include "DNA_grease_pencil_types.h"
#include "DNA_material_types.h"
#include "DNA_modifier_types.h"

#include "BLI_listbase.h"
#include "BLI_math_matrix.hh"
#include "BLI_math_vector.hh"
#include "BLI_string.h"

#include "BKE_attribute.hh"
#include "BKE_curves.hh"
#include "BKE_geometry_set.hh"
#include "BKE_grease_pencil.hh"
#include "BKE_lib_query.hh"
#include "BKE_material.hh"
#include "BKE_modifier.hh"

#include "BLO_read_write.hh"

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_build.hh"
#include "DEG_depsgraph_query.hh"

#include "GEO_join_geometries.hh"

#include "UI_interface_layout.hh"
#include "UI_resources.hh"

#include "BLT_translation.hh"

#include "WM_types.hh"

#include "RNA_access.hh"
#include "RNA_prototypes.hh"

#include "MOD_grease_pencil_util.hh"
#include "MOD_ui_common.hh"

namespace blender {

using bke::greasepencil::Drawing;
using bke::greasepencil::Layer;
using bke::greasepencil::LayerMask;

static void init_data(ModifierData *md)
{
  auto *mmd = reinterpret_cast<GreasePencilMaskModifierData *>(md);

  BLI_assert(MEMCMP_STRUCT_AFTER_IS_ZERO(mmd, modifier));

  MEMCPY_STRUCT_AFTER(mmd, DNA_struct_default_get(GreasePencilMaskModifierData), modifier);
  modifier::greasepencil::init_influence_data(&mmd->influence, false);
}

static void copy_data(const ModifierData *md, ModifierData *target, const int flag)
{
  const auto *mmd = reinterpret_cast<const GreasePencilMaskModifierData *>(md);
  auto *tmmd = reinterpret_cast<GreasePencilMaskModifierData *>(target);

  modifier::greasepencil::free_influence_data(&tmmd->influence);

  BKE_modifier_copydata_generic(md, target, flag);
  modifier::greasepencil::copy_influence_data(&mmd->influence, &tmmd->influence, flag);
}

static void free_data(ModifierData *md)
{
  auto *mmd = reinterpret_cast<GreasePencilMaskModifierData *>(md);
  modifier::greasepencil::free_influence_data(&mmd->influence);
}

static void foreach_ID_link(ModifierData *md, Object *ob, IDWalkFunc walk, void *user_data)
{
  auto *mmd = reinterpret_cast<GreasePencilMaskModifierData *>(md);
  modifier::greasepencil::foreach_influence_ID_link(&mmd->influence, ob, walk, user_data);

  walk(user_data, ob, (ID **)&mmd->object, IDWALK_CB_NOP);
}

static void update_depsgraph(ModifierData *md, const ModifierUpdateDepsgraphContext *ctx)
{
  auto *mmd = reinterpret_cast<GreasePencilMaskModifierData *>(md);
  if (mmd->object != nullptr) {
    /* The matte's evaluated geometry AND transform are sampled, so depend on both. This also
     * ensures the matte (and its Follow Peg) is evaluated before this object. */
    DEG_add_object_relation(
        ctx->node, mmd->object, DEG_OB_COMP_TRANSFORM, "Grease Pencil Cutter Modifier");
    DEG_add_object_relation(
        ctx->node, mmd->object, DEG_OB_COMP_GEOMETRY, "Grease Pencil Cutter Modifier");
  }
  DEG_add_depends_on_transform_relation(ctx->node, "Grease Pencil Cutter Modifier");
}

static bool is_disabled(const Scene * /*scene*/, ModifierData *md, bool /*use_render_params*/)
{
  auto *mmd = reinterpret_cast<GreasePencilMaskModifierData *>(md);
  return mmd->object == nullptr || mmd->object->type != OB_GREASE_PENCIL;
}

/**
 * A material slot on the masked object suitable for rasterizing the injected matte as a solid
 * silhouette. The mask pass renders mask layers through the same per-material draw as normal
 * geometry, so a matte assigned to a stroke-only material (Fill off) only contributes its
 * outline to the mask, not the filled interior it needs to clip against. Prefer the masked
 * object's own first Fill-enabled slot (almost any character part has one) over assuming slot 0
 * is fill-capable -- the previous hard-coded slot 0 broke as soon as that slot was a line-art
 * material, which is the common case (slot 0 added by default, then a fill material added after).
 */
static int find_fill_material_index(Object &masked_ob)
{
  for (int i = 0; i < masked_ob.totcol; i++) {
    const Material *ma = BKE_object_material_get(&masked_ob, short(i + 1));
    if (ma != nullptr && ma->gp_style != nullptr && (ma->gp_style->flag & GP_MATERIAL_FILL_SHOW))
    {
      return i;
    }
  }
  return 0;
}

/**
 * Collect the matte object's visible strokes at \a frame, each transformed into \a ctx->object's
 * (the masked object's) local space, joined into a single curves geometry. Returns false if the
 * matte has nothing to contribute.
 */
static bool gather_matte_curves(const ModifierEvalContext *ctx,
                                const Object &matte_ob,
                                const int frame,
                                bke::CurvesGeometry &r_curves)
{
  const GreasePencil &matte_gp = *static_cast<const GreasePencil *>(matte_ob.data);

  /* No material slots on the masked object means find_fill_material_index() can only return a
   * fallback 0 that references nothing: injecting matte strokes with material_index 0 against a
   * zero-sized material pool drives the GP draw engine's per-material lookup out of bounds (the
   * known mat-pool-overflow crash class). A normal GP object always ships a default slot; bail
   * defensively for the empty case rather than emit an invalid index. */
  if (ctx->object->totcol == 0) {
    return false;
  }

  /* Matte-object local space -> masked-object local space. The peg transforms live in the object
   * world matrices (Follow Peg post-multiplies them), so this maps the silhouette to where it is
   * seen on screen relative to the masked object. */
  const float4x4 matte_obj_to_local = ctx->object->world_to_object() * matte_ob.object_to_world();

  /* The fill-slot lookup scans the masked object's material slots and depends only on
   * ctx->object, so it is invariant across matte layers. Compute it once before the loop
   * rather than re-scanning totcol slots for every visible layer. */
  const int fill_index = find_fill_material_index(*ctx->object);

  Vector<bke::GeometrySet> parts;
  for (const Layer *layer : matte_gp.layers()) {
    if (!layer->is_visible()) {
      continue;
    }
    const Drawing *drawing = matte_gp.get_drawing_at(*layer, frame);
    if (drawing == nullptr || drawing->strokes().curves_num() == 0) {
      continue;
    }
    bke::CurvesGeometry curves = drawing->strokes();
    /* Fold in the matte layer's own transform, then map to the masked object's space. */
    curves.transform(matte_obj_to_local * layer->layer_to_object_space());

    /* The matte's material indices reference the matte object's slots, which do not exist on the
     * masked object. Remap them to a Fill-enabled slot on the masked object so the silhouette
     * rasterizes as a solid area into the mask buffer (see find_fill_material_index). */
    bke::MutableAttributeAccessor attributes = curves.attributes_for_write();
    bke::SpanAttributeWriter<int> materials = attributes.lookup_or_add_for_write_span<int>(
        "material_index", bke::AttrDomain::Curve);
    materials.span.fill(fill_index);
    materials.finish();

    parts.append(bke::GeometrySet::from_curves(bke::curves_new_nomain(std::move(curves))));
  }

  if (parts.is_empty()) {
    return false;
  }

  bke::GeometrySet joined = geometry::join_geometries(parts, {});
  Curves *joined_curves = joined.get_curves_for_write();
  if (joined_curves == nullptr || joined_curves->geometry.wrap().curves_num() == 0) {
    return false;
  }
  r_curves = std::move(joined_curves->geometry.wrap());
  return true;
}

static void modify_geometry_set(ModifierData *md,
                                const ModifierEvalContext *ctx,
                                bke::GeometrySet *geometry_set)
{
  const auto *mmd = reinterpret_cast<const GreasePencilMaskModifierData *>(md);

  if (mmd->object == nullptr || mmd->object == ctx->object) {
    return;
  }
  if (!geometry_set->has_grease_pencil()) {
    return;
  }

  Object *matte_ob = DEG_get_evaluated(ctx->depsgraph, mmd->object);
  if (matte_ob == nullptr || matte_ob->type != OB_GREASE_PENCIL || matte_ob->data == nullptr) {
    return;
  }

  GreasePencil &grease_pencil = *geometry_set->get_grease_pencil_for_write();
  const int frame = grease_pencil.runtime->eval_frame;

  /* Which of this object's layers receive the mask (respects the Influence layer filter). Captured
   * as indices BEFORE injecting the matte layer; appending does not shift existing indices. */
  IndexMaskMemory mask_memory;
  const IndexMask layer_mask = modifier::greasepencil::get_filtered_layer_mask(
      grease_pencil, mmd->influence, mask_memory);
  Vector<int64_t> target_layers(layer_mask.size());
  layer_mask.to_indices(target_layers.as_mutable_span());
  if (target_layers.is_empty()) {
    return;
  }

  bke::CurvesGeometry matte_curves;
  if (!gather_matte_curves(ctx, *matte_ob, frame, matte_curves)) {
    return;
  }

  /* The injected matte renders at the matte object's depth, which is typically behind the masked
   * object (and the matte object itself is still drawn). The gpencil mask pass depth-tests against
   * the scene, so a matte sitting behind the masked drawings is discarded exactly where it must
   * cover, leaving only its stroke outline as a mask. Masking is a screen-space operation, so the
   * matte's depth is otherwise irrelevant: project the matte onto the masked geometry's drawing
   * plane so it is co-planar with what it masks and survives the depth test. We project along the
   * drawing-plane NORMAL (not a fixed world axis): flattening a world axis would collapse the
   * silhouette into a line whenever that axis lies within the drawing plane (e.g. a front-view 2D
   * canvas drawn in the XZ plane). */
  {
    float3 plane_co(0.0f);
    float3 plane_no(0.0f);
    int64_t point_count = 0;
    for (const int64_t layer_i : target_layers) {
      const Layer &layer = grease_pencil.layer(layer_i);
      const float4x4 to_object = layer.layer_to_object_space();
      const float3x3 normal_mat = float3x3(to_object);
      if (const Drawing *drawing = grease_pencil.get_drawing_at(layer, frame)) {
        const bke::CurvesGeometry &masked_curves = drawing->strokes();
        for (const float3 &p : masked_curves.positions()) {
          plane_co += math::transform_point(to_object, p);
          point_count++;
        }
        for (const float3 &n : drawing->curve_plane_normals()) {
          plane_no += normal_mat * n;
        }
      }
    }
    /* Only project when the masked geometry defines a usable plane; otherwise leave the matte where
     * it is rather than risk collapsing it. */
    const float normal_len = math::length(plane_no);
    if (point_count > 0 && normal_len > 1e-6f) {
      plane_co /= float(point_count);
      plane_no /= normal_len;
      for (float3 &position : matte_curves.positions_for_write()) {
        position -= math::dot(position - plane_co, plane_no) * plane_no;
      }
    }
  }

  /* Inject the matte as a visible-but-opacity-0 layer with a unique name. It must be visible
   * (the draw engine skips hidden layers entirely) but opacity 0 keeps it from painting; the mask
   * pass still rasterizes its silhouette. The name must be unique so the mask resolves to it. */
  const int64_t matte_index = grease_pencil.layers().size();
  /* The GPU mask pipeline indexes mask layers in a fixed-size bitmap (GP_MAX_MASKBITS = 256 in
   * the gpencil draw engine's private header, not includable here). A layer whose index exceeds
   * that can't be used as a mask, so bail rather than inject a useless layer. */
  constexpr int64_t max_maskable_layer_index = 256;
  if (matte_index >= max_maskable_layer_index) {
    return;
  }
  grease_pencil.add_layers_with_empty_drawings_for_eval(1);

  Layer &matte_layer = grease_pencil.layer(matte_index);
  char uniq_name[128];
  BLI_snprintf(uniq_name, sizeof(uniq_name), "__nuclear_cutter__%s", md->name);
  matte_layer.set_name(uniq_name);
  matte_layer.set_visible(true);
  matte_layer.opacity = 0.0f;

  if (Drawing *matte_drawing = grease_pencil.get_drawing_at(matte_layer, frame)) {
    matte_drawing->strokes_for_write() = std::move(matte_curves);
    matte_drawing->tag_topology_changed();
  }

  const bool invert = (mmd->flag & MOD_GREASE_PENCIL_MASK_INVERT) != 0;
  for (const int64_t layer_i : target_layers) {
    if (layer_i == matte_index) {
      continue;
    }
    Layer &layer = grease_pencil.layer(layer_i);
    /* Don't double-add if a previous cutter modifier already referenced this matte layer. */
    if (BLI_findstring_ptr(
            &layer.masks, uniq_name, offsetof(GreasePencilLayerMask, layer_name)) != nullptr)
    {
      continue;
    }
    LayerMask *mask = MEM_new<LayerMask>(__func__, uniq_name);
    mask->flag = invert ? GP_LAYER_MASK_INVERT : 0;
    BLI_addtail(&layer.masks, reinterpret_cast<GreasePencilLayerMask *>(mask));
    /* Make sure masks are actually evaluated on this layer. */
    layer.base.flag &= ~GP_LAYER_TREE_NODE_HIDE_MASKS;
  }
}

static void panel_draw(const bContext *C, Panel *panel)
{
  uiLayout *layout = panel->layout;

  PointerRNA ob_ptr;
  PointerRNA *ptr = modifier_panel_get_property_pointers(panel, &ob_ptr);

  layout->use_property_split_set(true);

  layout->prop(ptr, "object", UI_ITEM_NONE, IFACE_("Matte"), ICON_NONE);
  layout->prop(ptr, "invert", UI_ITEM_NONE, std::nullopt, ICON_NONE);

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
  modifier_panel_register(region_type, eModifierType_GreasePencilMask, panel_draw);
}

static void blend_write(BlendWriter *writer, const ID * /*id_owner*/, const ModifierData *md)
{
  const auto *mmd = reinterpret_cast<const GreasePencilMaskModifierData *>(md);

  BLO_write_struct(writer, GreasePencilMaskModifierData, mmd);
  modifier::greasepencil::write_influence_data(writer, &mmd->influence);
}

static void blend_read(BlendDataReader *reader, ModifierData *md)
{
  auto *mmd = reinterpret_cast<GreasePencilMaskModifierData *>(md);

  modifier::greasepencil::read_influence_data(reader, &mmd->influence);
}

}  // namespace blender

ModifierTypeInfo modifierType_GreasePencilMask = {
    /*idname*/ "GreasePencilMask",
    /*name*/ N_("Cutter"),
    /*struct_name*/ "GreasePencilMaskModifierData",
    /*struct_size*/ sizeof(GreasePencilMaskModifierData),
    /*srna*/ &RNA_GreasePencilMaskModifier,
    /*type*/ ModifierTypeType::Constructive,
    /*flags*/ eModifierTypeFlag_AcceptsGreasePencil | eModifierTypeFlag_SupportsEditmode |
        eModifierTypeFlag_EnableInEditmode,
    /*icon*/ ICON_MOD_MASK,

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
