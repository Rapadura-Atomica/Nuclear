/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup modifiers
 *
 * Shared cage sampling for the Grease Pencil "Contour" (envelope) deform modifier and its bind /
 * envelope-setup operators.
 */

#pragma once

#include "BLI_math_vector_types.hh"
#include "BLI_vector.hh"

#include "DNA_object_types.h"

namespace blender::modifier::greasepencil {

/**
 * Sample a Contour-modifier cage object into a closed contour polygon, in cage-local space.
 * Mesh cage: its vertices in index order. Legacy curve cage: the first cyclic Bezier spline
 * tessellated by its preview resolution. When `deformed` is true the cage's evaluated geometry is
 * used (deformed mesh / `deformed_nurbs`); otherwise its rest (original) geometry. Returns false
 * when no usable contour of at least 3 points is found. Shared by the modifier and the bind /
 * envelope-setup operators so rest and deformed contours always correspond index-for-index.
 */
bool contour_sample_cage(const Object &cage, bool deformed, Vector<float3> &r_contour);

}  // namespace blender::modifier::greasepencil
