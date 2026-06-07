/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edobj
 *
 * Operators for the Nuclear peg rig: build a rig by binding Grease Pencil drawing objects to pegs.
 * Posing the pegs themselves is handled by the regular transform tools (see
 * `transform_convert_pegrig.cc`), which redirect a bound object's transform to its peg.
 */

#include "DNA_constraint_types.h"
#include "DNA_defs.h"
#include "DNA_object_types.h"
#include "DNA_pegrig_types.h"

#include "BLI_string.h"
#include "BLI_vector.hh"

#include "BKE_constraint.h"
#include "BKE_context.hh"
#include "BKE_lib_id.hh"
#include "BKE_main.hh"
#include "BKE_pegrig.hh"
#include "BKE_report.hh"

#include "DEG_depsgraph.hh"
#include "DEG_depsgraph_build.hh"

#include "ED_screen.hh"

#include "RNA_access.hh"
#include "RNA_define.hh"

#include "WM_api.hh"
#include "WM_types.hh"

#include "object_intern.hh"

namespace blender::ed::object {

static wmOperatorStatus pegrig_peg_new_exec(bContext *C, wmOperator *op)
{
  Main *bmain = CTX_data_main(C);

  Vector<Object *> targets;
  CTX_DATA_BEGIN (C, Object *, ob, selected_objects) {
    if (ob->type == OB_GREASE_PENCIL) {
      targets.append(ob);
    }
  }
  CTX_DATA_END;

  if (targets.is_empty()) {
    BKE_report(op->reports, RPT_ERROR, "Select one or more Grease Pencil objects");
    return OPERATOR_CANCELLED;
  }

  /* Reuse the rig already used by any selected object, otherwise create a new one. */
  PegRig *rig = nullptr;
  for (Object *ob : targets) {
    if (bConstraint *con = BKE_object_find_followpeg_constraint(ob)) {
      bFollowPegConstraint *data = static_cast<bFollowPegConstraint *>(con->data);
      if (data->rig != nullptr) {
        rig = data->rig;
        break;
      }
    }
  }
  if (rig == nullptr) {
    rig = BKE_pegrig_add(bmain, "PegRig");
    id_us_min(&rig->id);
  }

  /* If the active object already follows a peg in this rig, nest the new peg under it. */
  int parent_index = -1;
  if (Object *active = CTX_data_active_object(C)) {
    if (bConstraint *con = BKE_object_find_followpeg_constraint(active)) {
      bFollowPegConstraint *data = static_cast<bFollowPegConstraint *>(con->data);
      if (data->rig == rig) {
        parent_index = data->peg_index;
      }
    }
  }

  char name[64];
  RNA_string_get(op->ptr, "name", name);
  const int peg_index = BKE_pegrig_peg_add(rig, name[0] ? name : "Peg", parent_index);

  for (Object *ob : targets) {
    bConstraint *con = BKE_object_find_followpeg_constraint(ob);
    if (con == nullptr) {
      con = BKE_constraint_add_for_object(ob, "Follow Peg", CONSTRAINT_TYPE_FOLLOWPEG);
    }
    bFollowPegConstraint *data = static_cast<bFollowPegConstraint *>(con->data);
    if (data->rig != rig) {
      if (data->rig != nullptr) {
        id_us_min(&data->rig->id);
      }
      data->rig = rig;
      id_us_plus(&rig->id);
    }
    STRNCPY(data->peg_name, rig->pegs[peg_index].name);
    data->peg_index = peg_index;
    data->flag |= FOLLOWPEG_SET_INVERSE;
    DEG_id_tag_update(&ob->id, ID_RECALC_TRANSFORM);
  }

  rig->active_peg_index = peg_index;

  DEG_id_tag_update(&rig->id, ID_RECALC_PARAMETERS);
  DEG_relations_tag_update(bmain);
  WM_event_add_notifier(C, NC_OBJECT | ND_CONSTRAINT, nullptr);
  WM_event_add_notifier(C, NC_ID | NA_ADDED, nullptr);
  return OPERATOR_FINISHED;
}

void OBJECT_OT_pegrig_peg_new(wmOperatorType *ot)
{
  ot->name = "New Peg";
  ot->description = "Create a peg controlling the selected Grease Pencil drawings";
  ot->idname = "OBJECT_OT_pegrig_peg_new";

  ot->exec = pegrig_peg_new_exec;
  ot->poll = ED_operator_objectmode;

  ot->flag = OPTYPE_REGISTER | OPTYPE_UNDO;

  RNA_def_string(ot->srna, "name", "Peg", MAX_NAME, "Name", "Name for the new peg");
}

}  // namespace blender::ed::object
