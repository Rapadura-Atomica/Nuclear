/* SPDX-FileCopyrightText: 2024 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

/** \file
 * \ingroup edinterface
 */

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>

#include <fmt/format.h>

#include "BLI_fileops.h"
#include "BLI_listbase.h"
#include "BLI_map.hh"
#include "BLI_math_base.h"
#include "BLI_path_utils.hh"
#include "BLI_string.h"
#include "BLI_string_utf8.h"

#include "BLO_readfile.hh"

#include "BLT_translation.hh"

#include "BKE_blendfile.hh"
#include "BKE_global.hh"
#include "BKE_icons.h"
#include "BKE_main.hh"

#include "IMB_imbuf.hh"
#include "IMB_imbuf_types.hh"
#include "IMB_metadata.hh"
#include "IMB_thumbs.hh"

#include "RNA_access.hh"

#include "UI_interface_layout.hh"
#include "interface_intern.hh"

static void uiTemplateRecentFiles_tooltip_func(bContext & /*C*/,
                                               uiTooltipData &tip,
                                               uiBut * /*but*/,
                                               void *argN)
{
  char *path = (char *)argN;

  /* File name and path. */
  char dirname[FILE_MAX];
  char filename[FILE_MAX];
  BLI_path_split_dir_file(path, dirname, sizeof(dirname), filename, sizeof(filename));
  UI_tooltip_text_field_add(tip, filename, {}, UI_TIP_STYLE_HEADER, UI_TIP_LC_NORMAL);
  UI_tooltip_text_field_add(tip, dirname, {}, UI_TIP_STYLE_NORMAL, UI_TIP_LC_NORMAL);

  UI_tooltip_text_field_add(tip, {}, {}, UI_TIP_STYLE_SPACER, UI_TIP_LC_NORMAL);

  if (!BLI_exists(path)) {
    UI_tooltip_text_field_add(tip, N_("File Not Found"), {}, UI_TIP_STYLE_NORMAL, UI_TIP_LC_ALERT);
    return;
  }

  /* Blender version. */
  char version_str[128] = {0};
  /* Load the thumbnail from cache if existing, but don't create if not. */
  ImBuf *thumb = IMB_thumb_read(path, THB_LARGE);
  if (thumb) {
    /* Look for version in existing thumbnail if available. */
    IMB_metadata_get_field(
        thumb->metadata, "Thumb::Blender::Version", version_str, sizeof(version_str));
  }

  eFileAttributes attributes = BLI_file_attributes(path);
  if (!version_str[0] && !(attributes & FILE_ATTR_OFFLINE)) {
    /* Load Blender version directly from the file. */
    short version = BLO_version_from_file(path);
    if (version != 0) {
      SNPRINTF_UTF8(version_str, "%d.%01d", version / 100, version % 100);
    }
  }

  if (version_str[0]) {
    UI_tooltip_text_field_add(
        tip, fmt::format("Nuclear {}", version_str), {}, UI_TIP_STYLE_NORMAL, UI_TIP_LC_NORMAL);
    UI_tooltip_text_field_add(tip, {}, {}, UI_TIP_STYLE_SPACER, UI_TIP_LC_NORMAL);
  }

  BLI_stat_t status;
  if (BLI_stat(path, &status) != -1) {
    char date_str[FILELIST_DIRENTRY_DATE_LEN], time_st[FILELIST_DIRENTRY_TIME_LEN];
    bool is_today, is_yesterday;
    std::string day_string;
    BLI_filelist_entry_datetime_to_string(
        nullptr, int64_t(status.st_mtime), false, time_st, date_str, &is_today, &is_yesterday);
    if (is_today || is_yesterday) {
      day_string = (is_today ? N_("Today") : N_("Yesterday")) + std::string(" ");
    }
    UI_tooltip_text_field_add(tip,
                              fmt::format("{}: {}{}{}",
                                          N_("Modified"),
                                          day_string,
                                          (is_today || is_yesterday) ? "" : date_str,
                                          (is_today || is_yesterday) ? time_st : ""),
                              {},
                              UI_TIP_STYLE_NORMAL,
                              UI_TIP_LC_NORMAL);

    if (status.st_size > 0) {
      char size[16];
      BLI_filelist_entry_size_to_string(nullptr, status.st_size, false, size);
      UI_tooltip_text_field_add(
          tip, fmt::format("{}: {}", N_("Size"), size), {}, UI_TIP_STYLE_NORMAL, UI_TIP_LC_NORMAL);
    }
  }

  if (!thumb) {
    /* try to load from the blend file itself. */
    BlendThumbnail *data = BLO_thumbnail_from_file(path);
    thumb = BKE_main_thumbnail_to_imbuf(nullptr, data);
    if (data) {
      MEM_freeN(data);
    }
  }

  if (thumb) {
    UI_tooltip_text_field_add(tip, {}, {}, UI_TIP_STYLE_SPACER, UI_TIP_LC_NORMAL);
    UI_tooltip_text_field_add(tip, {}, {}, UI_TIP_STYLE_SPACER, UI_TIP_LC_NORMAL);

    uiTooltipImage image_data;
    float scale = (72.0f * UI_SCALE_FAC) / float(std::max(thumb->x, thumb->y));
    image_data.ibuf = thumb;
    image_data.width = short(float(thumb->x) * scale);
    image_data.height = short(float(thumb->y) * scale);
    image_data.border = true;
    image_data.background = uiTooltipImageBackground::Checkerboard_Themed;
    image_data.premultiplied = true;
    UI_tooltip_image_field_add(tip, image_data);
    IMB_freeImBuf(thumb);
  }
}

/* -------------------------------------------------------------------- */
/** \name Nuclear: Recent Files Thumbnail Grid
 *
 * Nuclear shows the recent projects as a grid of thumbnails (Krita-style welcome screen)
 * instead of a plain text list, so an artist recognizes a take by its drawing instead of
 * having to read near-identical file names.
 *
 * The thumbnail is the one embedded in the `.blend`/`.nuc` file itself (the last saved
 * state), read either from the system thumbnail cache or straight from the file header.
 * Because the buttons are rebuilt on every redraw, the resulting icons are kept in a
 * small process-wide cache keyed by file path and validated against the file's mtime.
 * \{ */

/** Height of a thumbnail tile, as a multiple of the default button height. */
#define RECENT_TILE_SCALE_Y 4.0f
/** Maximum number of cached thumbnail icons (LRU eviction beyond this). */
#define RECENT_THUMB_CACHE_MAX 100

namespace {

struct RecentThumbEntry {
  /** Managed icon owning the #ImBuf, or 0 when the file has no usable thumbnail. */
  int icon_id = 0;
  /** Modification time of the source file when the icon was created. */
  int64_t mtime = 0;
  /** Logical clock of the last use, for LRU eviction. */
  int64_t last_used = 0;
};

}  // namespace

static blender::Map<std::string, RecentThumbEntry> g_recent_thumbs;
static int64_t g_recent_thumb_clock = 0;

static void recent_thumb_entry_free(RecentThumbEntry &entry)
{
  if (entry.icon_id) {
    /* Deleting the icon also frees the #ImBuf it owns. */
    BKE_icon_delete(entry.icon_id);
    entry.icon_id = 0;
  }
}

/** Drop the least recently used entries until the cache fits #RECENT_THUMB_CACHE_MAX. */
static void recent_thumb_cache_trim()
{
  while (g_recent_thumbs.size() > RECENT_THUMB_CACHE_MAX) {
    std::string oldest_key;
    int64_t oldest_used = INT64_MAX;
    for (auto item : g_recent_thumbs.items()) {
      if (item.value.last_used < oldest_used) {
        oldest_used = item.value.last_used;
        oldest_key = item.key;
      }
    }
    if (oldest_key.empty()) {
      break;
    }
    RecentThumbEntry *entry = g_recent_thumbs.lookup_ptr(oldest_key);
    if (entry) {
      recent_thumb_entry_free(*entry);
    }
    g_recent_thumbs.remove(oldest_key);
  }
}

/**
 * Pad a thumbnail into a square buffer.
 *
 * Preview icons are always drawn stretched into a square region, so a 16:9 thumbnail would
 * be squashed. Letter-boxing it here keeps the drawing's proportions. Takes ownership of
 * \a ibuf and returns a buffer the caller owns (possibly the same one).
 */
static ImBuf *recent_thumb_make_square(ImBuf *ibuf)
{
  if (ibuf == nullptr) {
    return nullptr;
  }
  if (ibuf->x == ibuf->y) {
    return ibuf;
  }
  if (ibuf->byte_buffer.data == nullptr) {
    /* Only byte buffers are supported by the imbuf icon drawing. */
    IMB_freeImBuf(ibuf);
    return nullptr;
  }

  const int size = std::max(ibuf->x, ibuf->y);
  ImBuf *square = IMB_allocImBuf(size, size, 32, IB_byte_data);
  if (square == nullptr) {
    return ibuf;
  }

  const int offset_x = (size - ibuf->x) / 2;
  const int offset_y = (size - ibuf->y) / 2;
  const uint8_t *src = ibuf->byte_buffer.data;
  uint8_t *dst = square->byte_buffer.data;
  for (int y = 0; y < ibuf->y; y++) {
    memcpy(dst + (size_t(y + offset_y) * size + offset_x) * 4,
           src + size_t(y) * ibuf->x * 4,
           size_t(ibuf->x) * 4);
  }

  IMB_freeImBuf(ibuf);
  return square;
}

/** Read the thumbnail embedded in the file (or its cached version on disk). */
static ImBuf *recent_thumb_read(const char *filepath)
{
  /* Prefer the system thumbnail cache, it holds a higher resolution image. Don't create it
   * here, this runs while drawing. */
  ImBuf *thumb = IMB_thumb_read(filepath, THB_LARGE);
  if (thumb == nullptr) {
    /* Fall back to the small thumbnail stored in the file header. */
    BlendThumbnail *data = BLO_thumbnail_from_file(filepath);
    thumb = BKE_main_thumbnail_to_imbuf(nullptr, data);
    if (data) {
      MEM_freeN(data);
    }
  }
  return recent_thumb_make_square(thumb);
}

/**
 * Return an icon ID showing the file's own thumbnail, or 0 when there is none.
 * The icon is cached and re-created when the file changes on disk.
 */
static int recent_thumb_icon_ensure(const char *filepath)
{
  BLI_stat_t status;
  if (BLI_stat(filepath, &status) == -1) {
    /* Missing file (moved/deleted), the caller falls back to a placeholder icon. */
    return 0;
  }
  const int64_t mtime = int64_t(status.st_mtime);

  g_recent_thumb_clock++;

  const std::string key(filepath);
  if (RecentThumbEntry *entry = g_recent_thumbs.lookup_ptr(key)) {
    if (entry->mtime == mtime) {
      entry->last_used = g_recent_thumb_clock;
      return entry->icon_id;
    }
    /* File was saved again, the thumbnail is stale. */
    recent_thumb_entry_free(*entry);
    g_recent_thumbs.remove(key);
  }

  RecentThumbEntry entry;
  entry.mtime = mtime;
  entry.last_used = g_recent_thumb_clock;
  if (ImBuf *thumb = recent_thumb_read(filepath)) {
    /* The icon takes ownership of the buffer. */
    entry.icon_id = BKE_icon_imbuf_create(thumb);
  }
  /* A missing thumbnail is cached too (as icon 0), to avoid hitting the disk every redraw. */
  g_recent_thumbs.add_overwrite(key, entry);
  recent_thumb_cache_trim();

  return entry.icon_id;
}

/** Icon shown when the file has no embedded thumbnail (or is gone). */
static int recent_file_placeholder_icon(const char *filepath, const char *filename)
{
  if (!BLI_exists(filepath)) {
    return ICON_FILE_HIDDEN;
  }
  return BKE_blendfile_extension_check(filename) ? ICON_FILE_BLEND : ICON_FILE_BACKUP;
}

/** Draw a single recent file as a thumbnail tile with the file name underneath. */
static void recent_file_tile_draw(uiLayout &cell, const RecentFile *recent)
{
  const char *filename = BLI_path_basename(recent->filepath);

  uiLayout &thumb_row = cell.row(true);
  /* Scale (not #ui_units_y_set): the tile button itself must grow, otherwise it stays
   * one unit tall at the top of a taller row. */
  thumb_row.scale_y_set(RECENT_TILE_SCALE_Y);

  PointerRNA ptr = thumb_row.op("WM_OT_open_mainfile",
                                "",
                                ICON_NONE,
                                blender::wm::OpCallContext::InvokeDefault,
                                UI_ITEM_NONE);
  RNA_string_set(&ptr, "filepath", recent->filepath);
  RNA_boolean_set(&ptr, "display_file_selector", false);

  uiBlock *block = thumb_row.block();
  uiBut *but = ui_but_last(block);

  int icon_id = recent_thumb_icon_ensure(recent->filepath);
  if (icon_id == 0) {
    icon_id = recent_file_placeholder_icon(recent->filepath, filename);
  }
  /* NOLINTNEXTLINE: bugprone-suspicious-enum-usage */
  ui_def_but_icon(but, icon_id, UI_HAS_ICON | UI_BUT_ICON_PREVIEW);

  UI_but_func_tooltip_custom_set(
      but, uiTemplateRecentFiles_tooltip_func, BLI_strdup(recent->filepath), MEM_freeN);

  /* File name (without extension) under the thumbnail. */
  char label[FILE_MAXFILE];
  STRNCPY_UTF8(label, filename);
  BLI_path_extension_strip(label);

  uiLayout &label_row = cell.row(true);
  label_row.alignment_set(blender::ui::LayoutAlign::Center);
  label_row.label(label, ICON_NONE);
}

int uiTemplateRecentFiles(uiLayout *layout, int rows, int columns)
{
  if (columns <= 0) {
    /* Upstream behavior: a plain text list. */
    int i = 0;
    LISTBASE_FOREACH_INDEX (RecentFile *, recent, &G.recent_files, i) {
      if (i >= rows) {
        break;
      }

      const char *filename = BLI_path_basename(recent->filepath);
      PointerRNA ptr = layout->op("WM_OT_open_mainfile",
                                  filename,
                                  BKE_blendfile_extension_check(filename) ? ICON_FILE_BLEND :
                                                                            ICON_FILE_BACKUP,
                                  blender::wm::OpCallContext::InvokeDefault,
                                  UI_ITEM_NONE);
      RNA_string_set(&ptr, "filepath", recent->filepath);
      RNA_boolean_set(&ptr, "display_file_selector", false);

      uiBlock *block = layout->block();
      uiBut *but = ui_but_last(block);
      UI_but_func_tooltip_custom_set(
          but, uiTemplateRecentFiles_tooltip_func, BLI_strdup(recent->filepath), MEM_freeN);
    }

    return i;
  }

  uiLayout &grid = layout->column(false);
  uiLayout *tile_row = nullptr;

  int i = 0;
  LISTBASE_FOREACH_INDEX (RecentFile *, recent, &G.recent_files, i) {
    if (i >= rows) {
      break;
    }
    if ((i % columns) == 0) {
      tile_row = &grid.row(true);
    }
    recent_file_tile_draw(tile_row->column(true), recent);
  }

  /* Keep the grid rectangular by padding the last row with empty cells. */
  if (tile_row != nullptr && (i % columns) != 0) {
    for (int pad = i % columns; pad < columns; pad++) {
      tile_row->column(true).label("", ICON_NONE);
    }
  }

  return i;
}

/** \} */
