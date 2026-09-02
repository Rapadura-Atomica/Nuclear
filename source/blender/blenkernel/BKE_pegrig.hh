/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#pragma once

/** \file
 * \ingroup bke
 *
 * API for the Nuclear "peg rig" data-block (#PegRig): a standalone hierarchy of transform
 * controllers ("pegs") used to animate Grease Pencil objects in a Toon Boom Harmony style.
 * Pegs are not scene objects; a Grease Pencil object follows a peg through a Follow Peg
 * constraint (see #CONSTRAINT_TYPE_FOLLOWPEG).
 */

struct Main;
struct Object;
struct PegRig;
struct PegRigPeg;
struct bConstraint;

/** Create a new, empty peg rig data-block in `bmain`. */
PegRig *BKE_pegrig_add(Main *bmain, const char *name);

/**
 * Append a peg to the rig, giving it a unique name and default transform (scale 1, identity).
 *
 * \param parent_index: index of an existing peg to parent under, or -1 for a root peg.
 * \return the index of the new peg in #PegRig::pegs.
 */
int BKE_pegrig_peg_add(PegRig *rig, const char *name, int parent_index);

/**
 * Remove the peg at `peg_index` from the rig. Children of the removed peg are reparented to its
 * parent, remaining `parent_index` values are adjusted, and `active_peg_index` is updated.
 * Constraints that referenced the removed peg by name simply stop following.
 * \return true if a peg was removed.
 */
bool BKE_pegrig_peg_remove(PegRig *rig, int peg_index);

/** \return the peg with the given name, or null. */
PegRigPeg *BKE_pegrig_peg_find_by_name(PegRig *rig, const char *name);
/** \return the index of the peg with the given name, or -1. */
int BKE_pegrig_peg_index_by_name(const PegRig *rig, const char *name);

/** \return true if `ancestor` is a strict ancestor of `peg` in the parent chain. */
bool BKE_pegrig_peg_is_ancestor(const PegRig *rig, int ancestor, int peg);

/**
 * Reparent `peg_index` under `new_parent_index` (-1 for root). Rejects out-of-range indices and
 * any change that would introduce a cycle.
 * \return true if the parent was changed.
 */
bool BKE_pegrig_peg_reparent(PegRig *rig, int peg_index, int new_parent_index);

/**
 * Recompute the resolved world matrix (#PegRigPeg::world_mat) of every peg from its local
 * transform and parent chain. Robust to any peg ordering and to (corrupt) cycles.
 */
void BKE_pegrig_solve_world_matrices(PegRig *rig);

/**
 * Copy the resolved world matrix of a peg into `r_mat` (call #BKE_pegrig_solve_world_matrices
 * first). Writes identity and returns false when `peg_index` is out of range.
 */
bool BKE_pegrig_peg_world_matrix_get(const PegRig *rig, int peg_index, float r_mat[4][4]);

/**
 * Compute a peg's world matrix on the fly from its local transform and parent chain, writing the
 * result into `r_mat` without modifying `rig`. This is the read-only path used during evaluation:
 * it is safe to call concurrently from several objects sharing the same evaluated rig (unlike
 * #BKE_pegrig_solve_world_matrices, which caches into #PegRigPeg::world_mat). Writes identity and
 * returns false when `peg_index` is out of range.
 */
bool BKE_pegrig_peg_compute_world_matrix(const PegRig *rig, int peg_index, float r_mat[4][4]);

/**
 * Compute a peg's resolved opacity (its own times every ancestor's) on the fly, the read-only
 * counterpart of #BKE_pegrig_peg_compute_world_matrix. Writes 1.0 and returns false when
 * `peg_index` is out of range.
 */
bool BKE_pegrig_peg_compute_world_opacity(const PegRig *rig, int peg_index, float *r_opacity);

/**
 * Write a peg's local matrix (its own translation/rotation/scale about its pivot, excluding any
 * parent pegs) into `r_mat`. Writes identity and returns false when `peg_index` is out of range.
 */
bool BKE_pegrig_peg_local_matrix_get(const PegRig *rig, int peg_index, float r_mat[4][4]);

/**
 * \return the first Follow Peg constraint on `ob` (the constraint that binds the object to a peg),
 * or null if the object follows no peg.
 */
bConstraint *BKE_object_find_followpeg_constraint(const Object *ob);

/**
 * The peg an object is posed through. This is the peg its Follow Peg constraint binds it to, or
 * the rig's active peg when that one is the object's own peg or one of its ancestors (the Ctrl+B
 * "climb to parent / Peg Master" navigation of the Peg Pose tool).
 *
 * Every tool that reads or writes "the pose of this drawing" - the transform, its auto-key, Insert
 * and Delete Keyframe - has to agree on this peg, otherwise a keyframe lands on a controller other
 * than the one that moved.
 *
 * \return the rig, with the peg index in `r_peg_index`; null (index -1) when `ob` follows no peg.
 */
PegRig *BKE_pegrig_object_posing_peg_get(const Object *ob, int *r_peg_index);
