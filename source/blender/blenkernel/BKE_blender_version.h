/* SPDX-FileCopyrightText: 2023 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */
#pragma once

#include <stddef.h>

/** \file
 * \ingroup bke
 */

/**
 * The lines below use regex from scripts to extract their values,
 * Keep this in mind when modifying this file and keep this comment above the defines.
 *
 * \note Use #STRINGIFY() rather than defining with quotes.
 */

/** Blender major and minor version. */
#define BLENDER_VERSION 500
/** Blender patch version for bug-fix releases. */
#define BLENDER_VERSION_PATCH 0
/** Blender release cycle stage: alpha/beta/rc/release. */
#define BLENDER_VERSION_CYCLE release
/** Blender release type suffix. LTS or blank. */
#define BLENDER_VERSION_SUFFIX

/* Blender file format version. */
#define BLENDER_FILE_VERSION BLENDER_VERSION
#define BLENDER_FILE_SUBVERSION 122

/* Minimum Blender version that supports reading file written with the current
 * version. Older Blender versions will test this and cancel loading the file, showing a warning to
 * the user.
 *
 * See
 * https://developer.blender.org/docs/handbook/guidelines/compatibility_handling_for_blend_files/
 * for details. */
#define BLENDER_FILE_MIN_VERSION 405
#define BLENDER_FILE_MIN_SUBVERSION 85

/* Nuclear fork branding (shown in the window title bar instead of "Blender <version>").
 * Kept separate from the Blender version defines above, which are parsed by build scripts. */
#define NUCLEAR_NAME "Nuclear"

/* Nuclear fork version. These numbers are the single source of truth for the fork.
 *
 * NUCLEAR_BUILD is a monotonically increasing integer that MUST be bumped on every
 * released build: it is what the in-app auto-updater compares against the server
 * manifest (estacao/version.json) to decide whether a newer build is available.
 * `tools/nuclear_release.py` reads these defines to stamp the shipped
 * `nuclear_version.json` and the server manifest, so edit them here and nowhere else. */
#define NUCLEAR_VERSION_MAJOR 1
#define NUCLEAR_VERSION_MINOR 7
#define NUCLEAR_VERSION_PATCH 7
#define NUCLEAR_BUILD 20
/* Release stage suffix shown to users, e.g. "Beta"/"RC"/"Stable". */
#define NUCLEAR_VERSION_STAGE "Beta"

/* Stringify helpers, self-contained so this header does not depend on BLI_utildefines.h
 * (NUCLEAR_VERSION_STRING is used in adjacent-literal concatenation and must stay a
 * compile-time string literal). */
#define NUCLEAR_STRINGIFY_(x) #x
#define NUCLEAR_STRINGIFY(x) NUCLEAR_STRINGIFY_(x)

/* Version number only, no product name -> "1.0.0 (Beta)". Exposed to Python as
 * `_bpy._nuclear_version_string()` and shown in the About dialog so it never drifts
 * from these defines. */
#define NUCLEAR_VERSION_STRING_NO_NAME \
  NUCLEAR_STRINGIFY(NUCLEAR_VERSION_MAJOR) \
  "." NUCLEAR_STRINGIFY(NUCLEAR_VERSION_MINOR) "." NUCLEAR_STRINGIFY( \
      NUCLEAR_VERSION_PATCH) " (" NUCLEAR_VERSION_STAGE ")"

/* User-readable version, derived from the numbers above -> "Nuclear 1.0.0 (Beta)". */
#define NUCLEAR_VERSION_STRING NUCLEAR_NAME " " NUCLEAR_VERSION_STRING_NO_NAME

/* Compact version number only, no name/stage -> "1.6.0". Used where upstream showed the
 * bare Blender version (e.g. the splash-screen corner), so it reads as the Nuclear
 * version instead of the underlying Blender file-format version. */
#define NUCLEAR_VERSION_STRING_COMPACT \
  NUCLEAR_STRINGIFY(NUCLEAR_VERSION_MAJOR) \
  "." NUCLEAR_STRINGIFY(NUCLEAR_VERSION_MINOR) "." NUCLEAR_STRINGIFY(NUCLEAR_VERSION_PATCH)

/** User readable version string. */
const char *BKE_blender_version_string(void);

/** As above but does not show patch version. */
const char *BKE_blender_version_string_compact(void);

/** Returns true when version cycle is alpha, otherwise (beta, rc) returns false. */
bool BKE_blender_version_is_alpha(void);

/** Returns true when version suffix is LTS, otherwise returns false. */
bool BKE_blender_version_is_lts(void);

/**
 * Fill in given string buffer with user-readable formatted file version and subversion (if
 * provided).
 *
 * \param str_buff: a char buffer where the formatted string is written,
 * minimal recommended size is 8, or 16 if subversion is provided.
 *
 * \param file_subversion: the file subversion, if given value < 0, it is ignored, and only the
 * `file_version` is used.
 */
void BKE_blender_version_blendfile_string_from_values(char *str_buff,
                                                      const size_t str_buff_maxncpy,
                                                      const short file_version,
                                                      const short file_subversion);
