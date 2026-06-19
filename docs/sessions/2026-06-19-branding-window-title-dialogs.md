# Session: Branding visual — título da janela + diálogos

**Date**: 2026-06-19
**Tier**: 2 — Light
**Specialist**: general

## Task
Finalizar o branding visual (Blender→Nuclear). `splash.png` já foi alterada e está
marcada como resolvida (por decisão do usuário, até ele dizer o contrário). Seguir para
alterar o **título da janela** e os **diálogos**. O `.desktop` fica para quando houver o
SVG próprio; os ícones sofrerão um refactor COMPLETO mais à frente.

## What Was Done
- Título inicial da janela principal: literal `"Blender"` → `NUCLEAR_NAME` em
  `wm_window.cc:1043` (a re-escrita posterior do título via `WM_window_title` já usava
  `NUCLEAR_NAME`/`NUCLEAR_VERSION_STRING` — só o literal de criação faltava).
- Diálogos de suporte de GPU (`wm_platform_support.cc`): títulos `"Blender - "` →
  `NUCLEAR_NAME " - "` e as mensagens user-facing trocadas para "Nuclear"
  (compatibility / support / "will now close."). Adicionado `#include "BKE_blender_version.h"`.
- Diálogo de tarefa Win32 (`GHOST_SystemWin32.cc`): `L"Blender"` → `L"Nuclear"`.
- Título da janela do player de animação standalone (`wm_playanim.cc`):
  "Blender Animation Player" → "Nuclear Animation Player".
- Registro de divergência atualizado em `NUCLEAR_DIVERGENCE.md §3`.

## Decisions Made
- **Editar em C em vez do "truque de tradução":** essas strings disparam no startup
  **antes** de o seam `bpy.app.translations` do template Nuclear carregar (checagem de
  GPU/plataforma é muito cedo), então `_TRANSLATIONS` não as alcançaria. É a exceção
  explícita à regra "preferir upper layers sobre C".
- **NÃO alterar o `applicationName` "Blender"** passado ao Vulkan/XR
  (`GHOST_ContextVK.cc`, `GHOST_XrContext.cc`, `GHOST_XrGraphicsBindingVulkan.cc`):
  alguns drivers/GPU keyam workarounds nesse nome e ele não é user-facing. Risco > benefício.
- Mensagens dos diálogos mantidas dentro de `CTX_IFACE_` (traduzíveis); mudar o msgid é
  inócuo pois o projeto é en_US, sem `.po` de localização.
- `wm_playanim` usa o literal "Nuclear Animation Player" em vez de `NUCLEAR_NAME` para
  evitar adicionar um `#include` por causa de uma única string.
- Fora deste ciclo (decisão do usuário): `.desktop`, ícones SVG/Windows RC, URLs
  `docs.blender.org`/`extensions.blender.org`. `splash.png` resolvida.

## Modified Files
- `source/blender/windowmanager/intern/wm_window.cc` — título inicial da janela → `NUCLEAR_NAME` (≈1043).
- `source/blender/windowmanager/intern/wm_platform_support.cc` — `+#include "BKE_blender_version.h"`; títulos + mensagens dos diálogos de GPU (≈144/164/175/198/211/222).
- `intern/ghost/intern/GHOST_SystemWin32.cc` — título do diálogo de tarefa Win32 (≈2864).
- `source/blender/windowmanager/intern/wm_playanim.cc` — título da janela do player (≈1879).
- `tools/nuclear_claude/NUCLEAR_DIVERGENCE.md` — §3 atualizada (itens [feito] + nota Vulkan/XR).

## Verification (pendente de build)
- Build via distrobox: `distrobox enter blender -- bash -lc 'cd <repo>/Nuclear/build && ninja && ninja install'`.
- Título da janela: verificável direto na barra de título do binário recém-buildado.
- Diálogos de GPU: hardware-gated (só aparecem em suporte limitado/ausente) → validados por
  revisão de código + compile-clean. `STR_CONCAT` expande `suffix` como expressão, então
  `NUCLEAR_NAME " - "` concatena como literais adjacentes ("Nuclear - ").
- Win32: não-testável neste host (sem build Windows).
