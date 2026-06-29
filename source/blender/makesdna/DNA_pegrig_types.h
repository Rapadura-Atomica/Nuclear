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

  /* --- Squash & Stretch (Nuclear) — only meaningful when #PEGRIGPEG_SQUASH is set. ---
   * A volume-preserving non-uniform scale folded into the peg's local matrix in the XZ drawing
   * plane: the vertical (local-Z) span between #squash_anchor and #squash_tip drives a scale
   * along Z, compensated along X, anchored at #squash_anchor. Inert (identity) while the flag is
   * unset, so a peg without squash behaves exactly as before. See SquashFeature.md.
   * NOTE: pre-subversion-(500,121) files used a parent-space Y-axis model and are migrated by
   * clearing #PEGRIGPEG_SQUASH (see versioning_500.cc). */

  /** Bottom gizmo: the planted anchor point and pivot of the squash, in the peg's local space. */
  float squash_anchor[3];
  /** Top gizmo: with #squash_anchor defines the squash span, in the peg's local space. */
  float squash_tip[3];
  /** Rest vertical span (squash_tip.z - squash_anchor.z) captured when squash is enabled;
   * scale factor s = (current squash_tip.z - anchor.z) / rest_len. */
  float squash_rest_len;
  /** Orthogonal compensation amount [0..1]: 0 = pure axis scale, 1 = preserve area in the plane. */
  float squash_volume;
} PegRigPeg;

/** #PegRigPeg::flag */
typedef enum PegRigPeg_Flag {
  PEGRIGPEG_SELECT = 1 << 0,
  PEGRIGPEG_EXPAND = 1 << 1,
  /** Squash & Stretch active on this peg (the two squash gizmos appear and deform its followers). */
  PEGRIGPEG_SQUASH = 1 << 2,
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
