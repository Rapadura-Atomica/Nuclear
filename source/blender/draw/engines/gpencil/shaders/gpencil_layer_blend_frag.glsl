/* SPDX-FileCopyrightText: 2020-2022 Blender Authors
 *
 * SPDX-License-Identifier: GPL-2.0-or-later */

#include "infos/gpencil_infos.hh"

FRAGMENT_SHADER_CREATE_INFO(gpencil_layer_blend)

#include "gpencil_common_lib.glsl"

void main()
{
  float4 color;

  /* Remember, this is associated alpha (aka. pre-multiply). */
  color.rgb = textureLod(color_buf, screen_uv, 0).rgb;
  /* Stroke only render mono-chromatic revealage. We convert to alpha. */
  color.a = 1.0f - textureLod(reveal_buf, screen_uv, 0).r;

  /* Nuclear: Auto-Patch. The geometry pass already did the per-element masking (fill kept via
   * gp_mask_bypass, stroke discarded where the matte covers it), so re-applying the matte mask
   * here would wrongly cut the fill too. Force the matte term to 1 for auto-patch layers;
   * blend_opacity still applies. */
  float mask = (blend_auto_patch != 0) ? 1.0f : textureLod(mask_buf, screen_uv, 0).r;
  mask *= blend_opacity;

  frag_color = float4(1.0f, 0.0f, 1.0f, 1.0f);
  fragRevealage = float4(1.0f, 0.0f, 1.0f, 1.0f);

  blend_mode_output(blend_mode, color, mask, frag_color, fragRevealage);
}
