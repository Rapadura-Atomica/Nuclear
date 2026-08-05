/* SPDX-FileCopyrightText: 2022-2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "infos/overlay_edit_mode_infos.hh"

VERTEX_SHADER_CREATE_INFO(overlay_depth_gpencil)

#include "draw_grease_pencil_lib.glsl"
#include "draw_model_lib.glsl"
#include "draw_view_clipping_lib.glsl"
#include "draw_view_lib.glsl"
#include "select_lib.glsl"

#ifdef SELECT_ENABLE
/* Nuclear: same intersection the fragment shader uses for the 2D stroke order. Duplicated here
 * because in selection mode the depth has to be baked at vertex level (see below). */
float3 gp_select_ray_plane_intersection(float3 ray_ori, float3 ray_dir, float4 plane)
{
  float d = dot(plane.xyz, ray_dir);
  float3 plane_co = plane.xyz * (-plane.w / dot(plane.xyz, plane.xyz));
  float3 h = ray_ori - plane_co;
  float lambda = -dot(plane.xyz, h) / ((abs(d) < 1e-8f) ? 1e-8f : d);
  return ray_ori + ray_dir * lambda;
}
#endif

void main()
{
  float3 world_pos;
  float3 unused_N;
  float4 unused_color;
  float unused_strength;
  float2 unused_uv;

  gl_Position = gpencil_vertex(float4(uniform_buf.size_viewport, uniform_buf.size_viewport_inv),
                               world_pos,
                               unused_N,
                               unused_color,
                               unused_strength,
                               unused_uv,
                               gp_interp_flat.sspos,
                               gp_interp_flat.sspos_adj,
                               gp_interp_flat.aspect,
                               gp_interp_noperspective.thickness,
                               gp_interp_noperspective.hardness);

  /* Small bias to always be on top of the geom. */
  gl_Position.z -= 1e-3f;

#ifdef SELECT_ENABLE
  /* Nuclear: flatten the object onto gp_depth_plane so a click stacks the pieces the same way the
   * viewport shows them. The fragment shader cannot do it -- rewriting gl_FragDepth in selection
   * mode breaks the enforced early depth test -- but doing it here is exact: the plane is planar
   * in world space, so interpolating z/w across the triangle lands on the very same depth. In
   * selection mode the plane no longer comes from the bounding box; it encodes the render engine's
   * object order (#GreasePencil::compute_selection_depth_planes). */
  if (!gp_stroke_order3d) {
    bool is_persp = drw_view().winmat[3][3] == 0.0f;
    float3 ray_dir = is_persp ? (drw_view().viewinv[3].xyz - world_pos) : drw_view().viewinv[2].xyz;
    float3 isect = gp_select_ray_plane_intersection(world_pos, ray_dir, gp_depth_plane);
    float4 ndc = drw_point_world_to_homogenous(isect);
    gl_Position.z = (ndc.z / ndc.w) * gl_Position.w;
  }
#endif

  view_clipping_distances(world_pos);

  select_id_set(drw_custom_id());
}
