# Validação do auto-patch GP — caso B (occluder oculto) + cross-object visível

> **Data:** 2026-06-18 · **Branch:** `feat/gp-masks` (worktree `~/Documentos/GitHub/nuclear-gpmasks`)
> **Commit do feature+fix:** `897dcc4f519` ("feat(gp): auto-patch B/C + fix do fill cortado no layer-blend")
> **Complementa:** [`nuclear_auto_patch_bc_followup.md`](nuclear_auto_patch_bc_followup.md) (RESOLVIDO) ·
> [`nuclear_auto_patch_harmony_fidelity.md`](nuclear_auto_patch_harmony_fidelity.md) ·
> ADR [`docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md`](../../docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md)

> ✅ **NOTA 2026-06-19 — a validação §3–§6 SE CONFIRMA.** Uma revisão ao vivo deste dia chegou
> inicialmente a uma conclusão errada ("feature quebrado") por um **erro de método** (renderizar a cena
> `nuclear_autopatch_debug.blend`, cuja geometria está no **plano X-Y**, da vista **FRONT** em vez de
> **TOP** → via tudo de perfil). Re-medido da vista **TOP** correta, o cross-object/auto-patch
> **funciona**: máscara normal corta 7240px, auto-patch mantém o fill (corta 4849px, diff 4605px = fill
> preservado), e camada **stroke-only também é cortada** (4785px). Lição registrada na **§10**. O
> ON=OFF no cotovelo de um personagem em pose de descanso é **correto** (peças não se sobrepõem → nada a
> cortar); o corte aparece quando há sobreposição (movimento/pose).

## TL;DR

- O fix do auto-patch (corta **só a linha** do layer remendado onde o matte cobre, **mantém o fill**)
  está **validado para A, B e C** e **commitado** (`897dcc4f519`, 12 arquivos).
- O único pendente funcional que restava no follow-up — **validar B ao vivo (occluder com o ícone de
  olho desligado)** — foi confirmado por **amostragem de pixel** e por **demonstração visual** (toggle
  OFF→ON com o occluder oculto: o fill some e volta).
- **Importante (fonte de confusão):** no cross-object com occluder **opaco e na frente**, ligar/desligar
  o auto-patch resulta em imagem **idêntica** — e isso é **correto, não é bug**. O occluder tapa a
  região de qualquer jeito; o fill preservado do layer de baixo fica atrás dele, invisível. O efeito só
  é observável onde o que está embaixo aparece (occluder oculto = caso B, ou occluder semi-transparente).

---

## 1. Estado encontrado

Ao reabrir o trabalho, dois fatos não óbvios:

1. **O fix não estava commitado.** O último commit `d949910` ("native GP masks + cross-object cutter")
   **não** continha o push-constant `blend_auto_patch`. Todo o conjunto A/B/C/D **mais** o fix do blend
   (205 inserções em 5 arquivos do draw-engine + 2 arquivos de depsgraph/editor + `docs/` inteiro
   untracked) estava só no **working tree**.
2. **O binário estava defasado.** O binário em `build_gpmasks/bin/blender` era de `21:16`, mas
   `gpencil_layer_blend_frag.glsl` e `gpencil_cache_utils.cc` foram editados às `21:19` — **depois** do
   build. Como os shaders do draw-engine são embutidos no binário em build time, validar B nesse binário
   seria validar **código velho**. Por isso o passo 2.

> **Pegadinha do `git status`:** o worktree usa um **symlink** `lib/linux_x64 → <repo principal>/lib`,
> e o `git status` global aborta com *"expected submodule path 'lib/linux_x64' not to be a symbolic
> link"*. Foi por isso que dois arquivos modificados (`deg_builder_relations.cc`,
> `grease_pencil_layers.cc`) ficaram inicialmente invisíveis. **Sempre** rodar `git status`/`git add`
> com caminhos explícitos (`-- source/ docs/`) neste worktree.

## 2. Rebuild incremental

```sh
# o symlink de lib/ precisa existir (worktree não carrega lib/ — é make update-managed)
ln -s ~/Documentos/GitHub/Nuclear/lib/linux_x64 ~/Documentos/GitHub/nuclear-gpmasks/lib/linux_x64

distrobox enter blenderdev -- bash -lc \
  'cd ~/Documentos/GitHub/build_gpmasks && ninja -j8 && ninja install'
# -j8 e log na HOME (não /tmp — /tmp não é compartilhado de forma estável com o container)
```

Só 2 arquivos haviam mudado → recompila o shader gerado + relink rápido (18 passos). Binário resultante
`build_gpmasks/bin/blender` (2026-06-18 19:04), agora mais novo que o fonte do fix.

## 3. Validação de B — método objetivo (amostragem de pixel)

Cena: `~/Documentos/GitHub/nuclear_autopatch_debug.blend`, dois GP retangulares:

| Objeto | Papel | World bounds (x,y) | Material |
|---|---|---|---|
| `PartLower` | remendado (mascarado) | x∈[-1,1], y∈[-0.3,0.3] | linha **preta**, fill **salmão** (0.85,0.25,0.25) |
| `PartUpper` | occluder / matte | x∈[0,1.4], y∈[-0.5,0.5] | linha preta, fill **azul** (0.25,0.45,0.85) |

Máscara em `PartLower.Lines`: `object=PartUpper`, `invert=True`, `use_auto_patch` alternável.
O matte cobre a **metade direita** (x>0) de `PartLower`.

**Cenário B:** `PartUpper` oculto via `hide_set(True)` **e** `hide_render=True` (ícone de olho off).
Render OpenGL/GP (câmera ortho top, fundo conhecido), amostrando a cor real do pixel em pontos do mundo:

| Estado | FILL matte (0.5,0) | FILL livre (-0.5,0) | LINHA matte (0.5,0.3) | LINHA livre (-0.5,0.3) |
|---|---|---|---|---|
| `mask_off` (referência) | `(.77,.55,.55)` salmão | `(.77,.55,.55)` | `(0,0,0)` preto | `(0,0,0)` |
| `ap_off` (máscara normal) | **`(.51,.22,.25)`** alterado | `(.77,.55,.55)` | `(.22,.22,.22)` cortada | `(0,0,0)` |
| `ap_on` (**o fix**) | **`(.77,.55,.55)`** = fill cheio | `(.77,.55,.55)` | `(.22,.22,.22)` cortada | `(0,0,0)` |

Calibração de "nada/fundo" (ponto fora das peças) = `(.35,.45,.13)`.

**Leitura:**
- **Mod B funciona** — com `PartUpper` oculto, o matte **ainda é aplicado** a `PartLower` (`ap_off` ≠
  referência). Confirma `deg_builder_relations.cc` forçando a avaliação do occluder oculto + o sync
  diferido (`sync_referenced_mattes`/`cache_only`).
- **O fix do blend funciona em B** — com auto-patch ON, o fill na região do matte volta a ser
  **idêntico** ao fill sem máscara (`.77,.55,.55`), enquanto a linha continua cortada (`.22` vs preto).
  Corta só a linha, mantém o fill.
- **Sem regressão** na região livre (fill e linha intactos nos três estados).

## 4. Demonstração visual ao vivo (toggle OFF→ON, occluder oculto)

Mesmo dois objetos, `PartUpper` oculto, sobreposição na metade direita de `PartLower`:

| | Metade esquerda (livre) | Metade direita (sob o matte) |
|---|---|---|
| **auto-patch OFF** | salmão + contorno | **preto — fill cortado** |
| **auto-patch ON** | salmão + contorno | **salmão de volta; só o contorno some** |

Ao ligar o auto-patch o **fill salmão reaparece** na metade direita e o **contorno preto** ali é
removido — bate exatamente com a tabela de pixels da §3.

## 5. O caso cross-object com os dois objetos VISÍVEIS

Teste adicional: `PartUpper` visível, opaco, **na frente** (Z maior), cobrindo a metade direita de
`PartLower`. Resultado: **ON e OFF ficam visualmente idênticos.**

Isso é **esperado e correto**, não é falha:

- O occluder é **opaco** e está **na frente** → ele pinta aquela região por cima de qualquer jeito.
- O fill preservado de `PartLower` fica **atrás** do occluder, invisível.
- Logo, não há como distinguir ON de OFF nesse enquadramento — é oclusão, não bug.

O valor visível do auto-patch aparece em dois cenários, **não** nesse:
1. **Occluder oculto (caso B)** — preserva o fill que seria cortado (o caso dramático, §3/§4).
2. **Limpeza da costura** — sem contorno duplo na junção; visível quando o que está embaixo aparece
   (occluder semi-transparente, ou olhando a linha de costura).

## 6. A causa-raiz do bug (resumo técnico)

O fill cortado em B/C **não era depth** (hipótese antiga refutada ao vivo com debug de cor no frag).
A causa era o **passe de layer-blend re-aplicando o matte**:

- Layer mascarado é composto em **dois** momentos:
  1. **Geometria** (`gpencil_frag.glsl`): o `gp_mask_bypass` (empurrado pelo auto-patch) faz o **fill**
     ignorar a máscara e o **stroke** ser descartado onde o matte cobre. Até aqui o fill é mantido no
     `layer_fb`.
  2. **Blend do layer** (`gpencil_layer_blend_frag.glsl`): compõe o layer fazendo `color * mask`
     (`blend_mode_output`) — e **re-aplica o matte** ao layer inteiro, cortando o fill de volta.
- **Fix (3 linhas):** para layers auto-patch o blend ignora o matte (`mask = 1.0`), mantendo só
  `blend_opacity`. O stroke já saiu do `color_buf` no passe de geometria, então o fill é composto
  inteiro e o stroke fica cortado. Por isso "In Front" (depth) e o reroute `mask_bits` nunca ajudavam:
  o bypass chegava ao fill, mas no **passe errado**.

## 7. Arquivos do commit `897dcc4f519`

| Arquivo | Papel |
|---|---|
| `shaders/infos/gpencil_infos.hh` | push-constant `blend_auto_patch` no create-info `gpencil_layer_blend` |
| `shaders/gpencil_layer_blend_frag.glsl` | `mask = blend_auto_patch ? 1.0 : texture(mask_buf)` |
| `gpencil_cache_utils.cc` | empurra `blend_auto_patch = tgp_layer->auto_patch` no `blend_ps`; init/roteamento das masks |
| `gpencil_engine_c.cc` | passes de matte (mask_bits same-object, mattes cross-object) + sync diferido de mattes referenciados |
| `gpencil_engine_private.hh` | `tLayer.fill_ps` / `tLayer.auto_patch` / `Instance.referenced_mattes` / `tMatteRef` |
| `depsgraph/intern/builder/deg_builder_relations.cc` | **Mod B**: força avaliação (geom+transform) do objeto-matte mesmo oculto no viewport |
| `editors/grease_pencil/intern/grease_pencil_layers.cc` | **Mod C**: operador auto-patch com `matte_source` self/cross-object |
| `docs/decisions/2026-06-17-auto-patch-blend-mask-fix.md` | ADR |
| `docs/sessions/2026-06-17-*.md`, `docs/CHANGELOG.md` | logs de sessão / changelog |

## 8. Como reproduzir

1. Build (§2) e abrir o Nuclear com `nuclear_autopatch_debug.blend`.
2. **B (corte só-linha, occluder oculto):** em `PartLower`, layer `Lines` com mask `object=PartUpper`,
   `invert=True`, `use_auto_patch=True`. Esconder `PartUpper` (olho off / `hide_set`+`hide_render`).
   Alternar `use_auto_patch`:
   - **OFF:** metade direita de `PartLower` (região do matte) **some** (fill+linha cortados).
   - **ON:** fill salmão **inteiro**, só a linha cortada na metade direita.
3. **Cross-object visível (deve dar ON=OFF):** mostrar `PartUpper` opaco na frente. ON e OFF idênticos —
   esperado (§5).

Validação ao vivo via addon **blender-mcp** (painel "Blender MCP" → "Connect to MCP server", porta
9876): `execute_blender_code` + `get_viewport_screenshot`; medição objetiva por render OpenGL +
amostragem de `image.pixels`.

## 9. Pendências / limitações

- **Limitação menor conhecida:** a borda do stroke na costura é corte binário → leve aliasing de ~1px.
  Não é bug; melhoria opcional (corte com cobertura/AA) se incomodar em produção.
- **Gotcha de produção (já documentado):** a força do matte = opacidade do **fill do occluder**. Dentro
  do occluder o mask vale `1 - alpha_fill`; o corte do stroke só dispara com `mask < 0.001`
  (`gpencil_frag.glsl`). Occluder precisa de **fill opaco**; occluder semi-transparente → matte fraco →
  não corta.
- **Recomendado verificar em conteúdo real** (não só os retângulos sintéticos): fill com
  gradiente/textura, múltiplos layers, stroke de espessura variável — para sentir o aliasing da costura
  e a polaridade do `invert` no fluxo real.
- **Release:** este foi um rebuild incremental de dev. Para empacotar no updater do Nuclear, fazer build
  limpo no fluxo de release e **bumpar `NUCLEAR_BUILD`** (ver CLAUDE.md do fork).

---

## 10. ERRATA 2026-06-19 — a validação §3–§6 SE CONFIRMA (e a lição de método)

> **Contexto:** revisão ao vivo ("ler e consertar o cross-object"), via blender-mcp no binário de dev
> `build_gpmasks/bin/blender`. Esta seção registra **uma sequência de conclusões erradas e a correção
> final**, porque a lição de método vale mais que o erro.

### 10.1 — O ERRO (e por que enganou tanto)

A revisão concluiu, por horas, que "o auto-patch é inerte em camadas de material STROKE / o feature está
quebrado". **Isso era falso.** A causa foi um **erro de método de medição**, em duas camadas:

1. **Vista errada na cena de debug.** A `nuclear_autopatch_debug.blend` tem a geometria no **plano X-Y**
   (ver memória do projeto: "use vista TOP"). As medições foram feitas de **FRONT** → olhando a
   geometria **de perfil/borda** (renderizava um "bloco preto"); qualquer render-diff dá ~0 porque não se
   vê a região do corte. **GP plano X-Y → renderizar de TOP.**
2. **Sem overlap no personagem.** Os testes no `JulianoHeroiAtualização.blend` usaram o braço em pose de
   descanso (esticado) → `2braco` e `1antebraco` **não se sobrepõem** → não há nada pra cortar → 0. O
   `ON=OFF` no cotovelo é **correto** nesse caso (sem sobreposição). Além disso, self-patch por fill
   co-localizado quase não muda a linha (ela já fica na borda do fill) → 0 enganoso.

### 10.2 — A CORREÇÃO (medido da vista TOP correta, cena de debug, caso B occluder oculto)

| Estado | Δpx vs sem-máscara | Veredito |
|---|---|---|
| `ap_off` (máscara normal: corta linha **e** fill na metade do matte) | **7240** | ✅ corta |
| `ap_on` (auto-patch: mantém fill, corta só a linha) | **4849** | ✅ |
| `ap_on` vs `ap_off` (= o fill que o AP preserva) | **4605** | ✅ |
| PartLower tornado **stroke-only** (`show_fill=False`), máscara normal | **4785** | ✅ corta o stroke |

Conclusão: **§3–§6 procedem.** O cross-object/auto-patch **funciona** — corta a linha, mantém o fill, e
corta camada stroke; o Mod B (occluder oculto via sync diferido) também (foi medido com `hide_set`+
`hide_render`). Sanity de luz: ≈240k px não-pretos (a cena renderiza com cor em OpenGL render; o que era
"preto" era o perfil da geometria visto de FRONT).

### 10.3 — Protocolo de medição (pra não repetir o erro)

- **Descobrir o plano da geometria** (`bound_box` world) e renderizar **de frente pra ele** (X-Y→TOP,
  X-Z→FRONT, Y-Z→RIGHT). Conferir com 1 screenshot **antes** de confiar em qualquer número.
- **Garantir sobreposição real** entre alvo e matte na região visível, senão 0 é trivial.
- `render.opengl(view_context=True)` é válido (renderiza com cor); o **viewport screenshot** pode sair
  preto nessa cena — não confie nele, use o render.
- Documentar **qual vista/câmera** foi usada ao reivindicar "validado".

### 10.4 — O que de fato falta pro objetivo do usuário

O objetivo (junta de cutout: a linha que invade o fill da outra peça some, e se mantém no movimento) o
feature **já entrega** quando há sobreposição e auto-patch nas peças. O corte **mútuo** (as DUAS linhas
somem na zona comum) precisa de máscara nos **dois sentidos** — hoje o operador cria só um lado. Logo o
plano **Tier-2 original volta a valer**: o operador `grease_pencil.auto_patch` deve oferecer um modo
**mútuo** que cria também a máscara recíproca no occluder. Não é bug de engine; é conveniência de
workflow. (Rodar o operador manualmente nos dois sentidos já produz a junta limpa.)

### 10.5 — IMPLEMENTADO 2026-06-19: modo `mutual` no operador

`grease_pencil.auto_patch` ganhou a prop booleana **`mutual`** (cross-object). Quando ligada, além da
máscara no layer ativo (A→B), cria a **recíproca no occluder** (B→A, `auto_patch+invert`, matte = o
objeto ativo inteiro). Alvo da recíproca = a layer do occluder com o **mesmo nome** da patcheada (ex.:
ambas "Lines"), fallback pra layer ativa; guarda anti-duplicata. Arquivo:
`source/blender/editors/grease_pencil/intern/grease_pencil_layers.cc`.

**Validação:** uma chamada criou os dois lados (`PartLower.Lines→PartUpper` e
`PartUpper.Lines→PartLower`); primário corta **4849px**, recíproco **2147px** (cada um com o outro
oculto). **Nota:** inicialmente o caso AMBOS-VISÍVEIS dava diff 0; eu atribuí ao §5 (oclusão), mas
estava **errado** — era o bug de depth da §10.6. Com o fix da §10.6, ambos-visíveis passa a cortar.

### 10.6 — ROOT CAUSE + FIX 2026-06-19: matte sofria o depth test da cena (corte só com occluder oculto)

**Sintoma:** a matte cross-object só cortava a linha quando o objeto-occluder estava **OCULTO**; com a
peça-matte **VISÍVEL** (o caso real de dois braços sobrepostos) a costura não era cortada. Medido com
método confiável (processo fresco, vista TOP): `PU oculto→PL cortado 4133`; `PL oculto→PU cortado 1139`;
**ambos visíveis 0**. A matte era encontrada e submetida (instrumentação `found=1`), mas não cortava.

**Root cause (confirmada por bisseção — desabilitar o depth test fez ambos-visíveis ir 0→573):** o frag
`gpencil_frag.glsl` faz um **teste manual de profundidade** (`if gl_FragCoord.z > scene_depth discard`).
A matte (silhueta de fill do occluder) é renderizada por esse mesmo shader no mask buffer; quando o
occluder está **visível**, sua geometria está no `gp_scene_depth_tx`, então o depth test **descarta a
própria matte** na zona de sobreposição (atrás do que está na frente) → mask buffer vazio ali → o stroke
patcheado não é cortado. Com o occluder oculto, ele não está no depth → matte inteira → corta. (Era a
suspeita do comentário "KNOWN BUG" em `gpencil_cache_utils.cc`:316–419.)

**Fix:** novo push-constant `gp_in_mask_pass` (create-info `gpencil_geometry`). Setado **1** no `fill_ps`
(que é submetido só como matte) e **0** no passe normal; o frag pula o scene-depth-test quando =1. A
matte é uma silhueta num buffer isolado, não geometria oclusa — não deve sofrer o depth da cena.
Cirúrgico: o desenho normal continua com depth test. Arquivos: `gpencil_frag.glsl`, `infos/gpencil_infos.hh`,
`gpencil_engine_c.cc` (`pass`=0, `fill_pass`=1).

**Validação (fresh-process):** ambos-visíveis **0→573**; (B)/(C) inalterados (4133/1139). Visual: duas
peças cor-pele sobrepostas e **visíveis** — a faixa preta de costura na junta **some** e as peles se
conectam numa silhueta contínua (ON vs OFF). Limitação conhecida: o mesmo depth-skip ainda **não** foi
aplicado ao caminho same-object (`mask_bits`/`geom_ps`), só ao cross-object (`fill_ps`); self-patch com
matte visível pode precisar de tratamento análogo (não testado).
