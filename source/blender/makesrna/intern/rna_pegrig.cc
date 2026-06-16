/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup RNA
 */

#include <climits>
#include <cstdlib>

#include "RNA_define.hh"
#include "RNA_enum_types.hh"

#include "rna_internal.hh"

#include "DNA_defs.h"
#include "DNA_pegrig_types.h"

#include "BLT_translation.hh"

#ifdef RNA_RUNTIME

#  include <fmt/format.h>

#  include "BLI_string.h"

#  include "BKE_main.hh"
#  include "BKE_pegrig.hh"
#  include "BKE_report.hh"

#  include "DEG_depsgraph.hh"

#  include "WM_api.hh"
#  include "WM_types.hh"

static void rna_PegRig_update(Main * /*bmain*/, Scene * /*scene*/, PointerRNA *ptr)
{
  /* Tag the rig's parameters so objects following its pegs re-evaluate. */
  DEG_id_tag_update(ptr->owner_id, ID_RECALC_PARAMETERS);
  WM_main_add_notifier(NC_OBJECT | ND_TRANSFORM, nullptr);
}

static PegRigPeg *rna_PegRig_pegs_new(PegRig *rig, const char *name, const int parent_index)
{
  const int index = BKE_pegrig_peg_add(rig, name, parent_index);
  DEG_id_tag_update(&rig->id, ID_RECALC_PARAMETERS);
  WM_main_add_notifier(NC_OBJECT | ND_CONSTRAINT, nullptr);
  return &rig->pegs[index];
}

static void rna_PegRig_pegs_remove(PegRig *rig, ReportList *reports, PointerRNA *peg_ptr)
{
  PegRigPeg *peg = static_cast<PegRigPeg *>(peg_ptr->data);
  const int index = int(peg - rig->pegs);
  if (index < 0 || index >= rig->pegs_num) {
    BKE_report(reports, RPT_ERROR, "Peg not found in this rig");
    return;
  }
  BKE_pegrig_peg_remove(rig, index);
  peg_ptr->invalidate();

  DEG_id_tag_update(&rig->id, ID_RECALC_PARAMETERS);
  WM_main_add_notifier(NC_OBJECT | ND_CONSTRAINT, nullptr);
}

static std::optional<std::string> rna_PegRigPeg_path(const PointerRNA *ptr)
{
  const PegRigPeg *peg = static_cast<const PegRigPeg *>(ptr->data);
  char name_esc[sizeof(peg->name) * 2];
  BLI_str_escape(name_esc, peg->name, sizeof(name_esc));
  return fmt::format("pegs[\"{}\"]", name_esc);
}

#else

static void rna_def_pegrig_peg(BlenderRNA *brna)
{
  StructRNA *srna;
  PropertyRNA *prop;

  srna = RNA_def_struct(brna, "PegRigPeg", nullptr);
  RNA_def_struct_sdna(srna, "PegRigPeg");
  RNA_def_struct_path_func(srna, "rna_PegRigPeg_path");
  RNA_def_struct_ui_text(srna, "Peg", "A transform controller within a peg rig");

  prop = RNA_def_property(srna, "name", PROP_STRING, PROP_NONE);
  RNA_def_property_string_sdna(prop, nullptr, "name");
  RNA_def_property_ui_text(prop, "Name", "Unique name of the peg within the rig");
  RNA_def_struct_name_property(srna, prop);

  prop = RNA_def_property(srna, "parent_index", PROP_INT, PROP_NONE);
  RNA_def_property_int_sdna(prop, nullptr, "parent_index");
  RNA_def_property_clear_flag(prop, PROP_ANIMATABLE);
  RNA_def_property_ui_text(prop, "Parent Index", "Index of the parent peg, or -1 for a root peg");

  prop = RNA_def_property(srna, "translation", PROP_FLOAT, PROP_TRANSLATION);
  RNA_def_property_float_sdna(prop, nullptr, "translation");
  RNA_def_property_ui_text(prop, "Translation", "Location of the peg in its local space");
  RNA_def_property_update(prop, 0, "rna_PegRig_update");

  prop = RNA_def_property(srna, "rotation", PROP_FLOAT, PROP_EULER);
  RNA_def_property_float_sdna(prop, nullptr, "rotation");
  RNA_def_property_ui_text(prop, "Rotation", "Euler rotation of the peg around its pivot");
  RNA_def_property_update(prop, 0, "rna_PegRig_update");

  prop = RNA_def_property(srna, "scale", PROP_FLOAT, PROP_XYZ);
  RNA_def_property_float_sdna(prop, nullptr, "scale");
  RNA_def_property_ui_text(prop, "Scale", "Scale of the peg around its pivot");
  RNA_def_property_update(prop, 0, "rna_PegRig_update");

  prop = RNA_def_property(srna, "pivot", PROP_FLOAT, PROP_TRANSLATION);
  RNA_def_property_float_sdna(prop, nullptr, "pivot");
  RNA_def_property_ui_text(prop, "Pivot", "Pivot point for rotation and scale, in local space");
  RNA_def_property_update(prop, 0, "rna_PegRig_update");
}

static void rna_def_pegrig_pegs(BlenderRNA *brna, PropertyRNA *cprop)
{
  StructRNA *srna;
  FunctionRNA *func;
  PropertyRNA *parm;

  RNA_def_property_srna(cprop, "PegRigPegs");
  srna = RNA_def_struct(brna, "PegRigPegs", nullptr);
  RNA_def_struct_sdna(srna, "PegRig");
  RNA_def_struct_ui_text(srna, "Pegs", "Collection of pegs");

  func = RNA_def_function(srna, "new", "rna_PegRig_pegs_new");
  RNA_def_function_ui_description(func, "Add a new peg to the rig");
  parm = RNA_def_string(func, "name", "Peg", MAX_NAME, "Name", "Name of the new peg");
  RNA_def_parameter_flags(parm, PropertyFlag(0), PARM_REQUIRED);
  parm = RNA_def_int(func,
                     "parent_index",
                     -1,
                     -1,
                     INT_MAX,
                     "Parent Index",
                     "Index of the parent peg, or -1 for a root peg",
                     -1,
                     INT_MAX);
  /* return */
  parm = RNA_def_pointer(func, "peg", "PegRigPeg", "", "Newly created peg");
  RNA_def_function_return(func, parm);

  func = RNA_def_function(srna, "remove", "rna_PegRig_pegs_remove");
  RNA_def_function_flag(func, FUNC_USE_REPORTS);
  RNA_def_function_ui_description(func, "Remove a peg from the rig");
  parm = RNA_def_pointer(func, "peg", "PegRigPeg", "", "Peg to remove");
  RNA_def_parameter_flags(parm, PROP_NEVER_NULL, PARM_REQUIRED | PARM_RNAPTR);
  RNA_def_parameter_clear_flags(parm, PROP_THICK_WRAP, ParameterFlag(0));
}

static void rna_def_pegrig(BlenderRNA *brna)
{
  StructRNA *srna;
  PropertyRNA *prop;

  rna_def_pegrig_peg(brna);

  srna = RNA_def_struct(brna, "PegRig", "ID");
  RNA_def_struct_ui_text(
      srna, "Peg Rig", "Peg rig data-block holding a hierarchy of cut-out animation controllers");
  RNA_def_struct_ui_icon(srna, ICON_ARMATURE_DATA);

  prop = RNA_def_property(srna, "pegs", PROP_COLLECTION, PROP_NONE);
  RNA_def_property_collection_sdna(prop, nullptr, "pegs", "pegs_num");
  RNA_def_property_struct_type(prop, "PegRigPeg");
  RNA_def_property_ui_text(prop, "Pegs", "Pegs in this rig");
  rna_def_pegrig_pegs(brna, prop);

  prop = RNA_def_property(srna, "active_peg_index", PROP_INT, PROP_NONE);
  RNA_def_property_int_sdna(prop, nullptr, "active_peg_index");
  RNA_def_property_clear_flag(prop, PROP_ANIMATABLE);
  RNA_def_property_ui_text(prop, "Active Peg Index", "Index of the active peg, or -1 when none");

  /* common */
  rna_def_animdata_common(srna);
}

void RNA_def_pegrig(BlenderRNA *brna)
{
  rna_def_pegrig(brna);
}

#endif
