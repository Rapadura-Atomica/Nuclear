/* SPDX-FileCopyrightText: 2024 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup modifiers
 *
 * Shared sampling for the Grease Pencil "Curve" deform modifier and its bind operator.
 *
 * The deformer is an arc-length spline bind (Toon Boom style): each drawing point stores the
 * arc-length parameter `u` of its nearest point on the rest curve plus its offset expressed in the
 * curve's local frame at that point. Reconstructing `pos(u) + frame(u) * offset` on the deformed
 * curve makes the rest pose an identity and bends each section locally — which is what 2D artists
 * expect, unlike the global stretch of the mesh Curve modifier.
 *
 * The frame is intentionally *locked to the drawing plane* (plane normal fixed, in-plane normal =
 * tangent rotated 90 degrees) rather than the curve's 3D rotation-minimizing frame. A 3D frame
 * twists out of plane and flips at inflection points / sharp bends, which contorts the stroke; the
 * planar frame cannot, as long as the tangent varies continuously.
 */

#pragma once

#include "BLI_math_matrix.hh"
#include "BLI_math_vector.hh"

#include "BKE_anim_path.h"

#include "DNA_object_types.h"

namespace blender::greasepencil_curve {

/* Internal attribute names holding the per-point binding. */
inline constexpr const char *ATTR_U = ".gp_curve_u";
inline constexpr const char *ATTR_OFFSET = ".gp_curve_off";

/**
 * Evaluate the deform curve at arc-length parameter `u` in [0, 1], in the curve object's local
 * space. `plane_normal` is the (unit-ish) drawing-plane normal in the curve's local space.
 * `r_frame`'s columns are an orthonormal frame [tangent, in-plane-normal, plane-normal] locked to
 * that plane, used to store and reconstruct point offsets. Returns false if the curve has no
 * evaluated path.
 */
inline bool sample_curve(const Object &curve_ob,
                         const float u,
                         const float3 &plane_normal,
                         float3 &r_pos,
                         float3x3 &r_frame)
{
  float vec[4], dir[3], quat[4];
  if (!BKE_where_on_path(
          &curve_ob, math::clamp(u, 0.0f, 1.0f), vec, dir, quat, nullptr, nullptr))
  {
    return false;
  }
  r_pos = float3(vec[0], vec[1], vec[2]);

  const float3 n = math::normalize(plane_normal);
  /* Project the curve tangent into the drawing plane so the frame stays planar. */
  float3 t = float3(dir[0], dir[1], dir[2]);
  t = t - math::dot(t, n) * n;
  const float t_len = math::length(t);
  if (t_len < 1e-6f) {
    /* Degenerate (tangent parallel to the plane normal): pick any in-plane axis. */
    const float3 ref = (math::abs(n.x) < 0.9f) ? float3(1.0f, 0.0f, 0.0f) :
                                                 float3(0.0f, 0.0f, 1.0f);
    t = math::normalize(math::cross(n, ref));
  }
  else {
    t = t / t_len;
  }
  const float3 in_plane_normal = math::cross(n, t);

  float3x3 frame;
  frame[0] = t;
  frame[1] = in_plane_normal;
  frame[2] = n;
  r_frame = frame;
  return true;
}

}  // namespace blender::greasepencil_curve
