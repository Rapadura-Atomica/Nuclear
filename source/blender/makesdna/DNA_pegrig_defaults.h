/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup DNA
 */

#pragma once

/* clang-format off */

/* -------------------------------------------------------------------- */
/** \name PegRig Struct
 * \{ */

#define _DNA_DEFAULT_PegRig \
  { \
    .pegs = NULL, \
    .pegs_num = 0, \
    .active_peg_index = -1, \
  }

/* Per-peg defaults (scale = 1, inert squash params) are applied by BKE_pegrig_peg_add, since pegs
 * live in a separately-allocated array rather than in the struct itself. */

/** \} */

/* clang-format on */
