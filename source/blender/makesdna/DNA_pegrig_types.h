/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup DNA
 *
 * Nuclear "peg rig": a standalone data-block holding a hierarchy of pegs (transform
 * controllers, Toon Boom Harmony style). Pegs are *not* scene objects; a Grease Pencil
 * object follows a peg through a #bFollowPegConstraint. One #PegRig usually represents
 * one character.
 */

#pragma once

#include "DNA_ID.h"

struct AnimData;

/**
 * A single peg: a named transform controller in the rig hierarchy.
 *
 * Parenting is by index into the owning #PegRig::pegs array (#parent_index == -1 for a root
 * peg). The on-disk transform is the UI representation (#translation / #rotation / #scale around
 * #pivot); the resolved #world_mat is runtime only and rebuilt by #BKE_pegrig_solve_world_matrices.
 */
typedef struct PegRigPeg {
  /** Unique within the rig; used for RNA lookup (`pegs["arm"]`) and constraint references. */
  char name[64];
  /** Index of the parent peg in #PegRig::pegs, or -1 for a root peg. */
  int parent_index;
  /** #PegRigPeg_Flag. */
  short flag;
  char _pad[2];

  /** Local transform (UI). Rotation and scale happen around #pivot, in the peg's local space. */
  float translation[3];
  float rotation[3];
  float scale[3];
  float pivot[3];

  /**
   * Resolved world matrix (peg-space, before any object transform), runtime only.
   * Recomputed from the parent chain each evaluation; not meaningful when read from disk.
   */
  float world_mat[4][4];
} PegRigPeg;

/** #PegRigPeg::flag */
typedef enum PegRigPeg_Flag {
  PEGRIGPEG_SELECT = 1 << 0,
  PEGRIGPEG_EXPAND = 1 << 1,
} PegRigPeg_Flag;

typedef struct PegRig {
#ifdef __cplusplus
  /** See #ID_Type comment for why this is here. */
  static constexpr ID_Type id_type = ID_PG;
#endif

  ID id;
  /** Animation data (must be immediately after id for utilities to use it). */
  struct AnimData *adt;

  /** Array of #pegs_num pegs. Parenting is by index within this array. */
  PegRigPeg *pegs;
  int pegs_num;
  /** Index of the active peg in #pegs, or -1 when none. */
  int active_peg_index;
} PegRig;
