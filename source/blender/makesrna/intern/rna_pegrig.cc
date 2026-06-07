/* SPDX-FileCopyrightText: 2026 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup RNA
 */

#include <cstdlib>

#include "RNA_define.hh"
#include "RNA_enum_types.hh"

#include "rna_internal.hh"

#include "DNA_pegrig_types.h"

#include "BLT_translation.hh"

#ifdef RNA_RUNTIME

#  include <fmt/format.h>

#  include "BLI_string.h"

#  include "BKE_main.hh"

#  include "DEG_depsgraph.hh"

#  include "WM_api.hh"
#  include "WM_types.hh"

static void rna_PegRig_update(Main * /*bmain*/, Scene * /*scene*/, PointerRNA *ptr)
{
  /* Tag the rig's parameters so objects following its pegs re-evaluate. */
  DEG_id_tag_update(ptr->owner_id, ID_RECALC_PARAMETERS);
  WM_main_add_notifier(NC_OBJECT | ND_TRANSFORM, nullptr);
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
