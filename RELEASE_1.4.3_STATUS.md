# Nuclear 1.4.3 (Beta) — status do release

> Handoff do trabalho da sessão de 2026-06-29. Documenta **o que foi feito** e **o que falta**.
> Branch de trabalho: `integration/1.4.3-audit`. Produção atual no servidor: **1.4.2 / build 7**.

---

## TL;DR

A 1.4.3 unifica a auditoria de crash/freeze + squash + reset operators na mainline 1.4.x e
recebeu **duas rodadas de auditoria de performance**.

**Estado:** ✅ **PUBLICADA (2026-06-29) — Nuclear 1.4.3 (Beta) / `NUCLEAR_BUILD = 8`.**
A regressão do squash foi corrigida (ver abaixo) e validada ao vivo no rig da Carolina; o release foi
empacotado, verificado e publicado. Detalhes canônicos em `tools/nuclear_claude/CLAUDE.md` §10.

### Resolução do bloqueador do squash (o que de fato consertou)
A causa não era só o eixo: o **enable** gravava um `anchor→tip` inclinado (do bounding-box do mundo) e
a **compensação de área em X vinha ligada** (`squash_volume=1`), então a peça esticava/deslizava em X.
Correção final (commit `ab145b8`):
- **Driver** (`pegrig.cc`): escala axis-aligned ao **X/Z local**, ponto fixo = **pivot da peg** (o
  mesmo da rotação/escala) → deforma a partir do pivot, sem deslizar. `squash_volume` default **0**.
- **Enable** (`object_pegrig.cc`): anchor nasce **no pivot**, tip reto acima (eixo = Z local puro).
- **Gizmo** (`nuclear_squash_gizmo.py`): tip travado acima do anchor (eixo sempre vertical).
- **Bônus**: gizmo de pontos do envelope/Contour (`nuclear_contour_gizmo.py`, commit `ee17552`).

> Histórico abaixo preservado (a análise original propunha escalar ao longo do `anchor→tip`; na
> prática isso ainda ia diagonal porque o enable inclinava o eixo — o conserto foi travar no pivot).

---

## O que foi feito

### 1. Junção numa versão única (1.4.3)
- Mergeada a branch `fix/crash-freeze-audit` (base 1.3.2) sobre a `Nuclear` (1.4.2 / build 7).
  Merge automático limpo, sem conflitos. Commit **`580d349`**.
- Coexiste com as features da 1.4.2 (auto-rig, formato `.nuc`, persistência de layout do Peg Graph).
- Bump de versão **1.4.2 → 1.4.3, NUCLEAR_BUILD 7 → 8** em `BKE_blender_version.h`. Commit **`d5766be`**.
- Trouxe da auditoria: fix do freeze (~1000 frames), perf (defer/throttle), **squash & stretch no
  plano XZ**, **operadores de reset** (envelope/contour/curve).

### 2. Rodada 1 da auditoria — bugs (commits `068557a`, `9890762`)
- **Squash "pulava" ao ativar em peg rotacionada** — `squash_rest_len` passou a ser o vão vertical
  (Z) em vez da distância 3D, coerente com o driver Z-only. (enable + reset em `object_pegrig.cc`)
- **do-version (subversion 500→121)** limpa `PEGRIGPEG_SQUASH` de arquivos pré-1.4.3 (o squash mudou
  de eixo Y→Z sem migração possível; sem isso virava no-op silencioso). `versioning_500.cc`.
- **Peg Graph dessincronizava** — o rebuild diferido marcava a assinatura como atual ANTES do rebuild
  e sem try/except; agora marca só após sucesso, com try/except por árvore. `nuclear_peg_graph.py`.
- **`_register_curve_reset_panel`** não engole mais a falha de registro em silêncio.
- Perf: `_graph_signature` de 3×→1× varredura; cache de pontos locais do overlay (`_OUTLINE_LOCAL_CACHE`).

### 3. Rodada 2 da auditoria — performance (commit `c9cd016`)
- **E1 (maior ganho) — avaliação do PegRig O(N) com cache:** o solve `BKE_pegrig_solve_world_matrices`
  nunca rodava na avaliação; cada Follow Peg recomputava a cadeia do zero (O(N·prof)/objeto/frame).
  Agora há um nó de depsgraph **`PEGRIG_SOLVE`** (componente PARAMETERS, entre EVAL e EXIT → vê
  transforms animados/dirigidos) e o constraint lê `BKE_pegrig_peg_world_matrix_get` O(1).
  Arquivos: `deg_node_operation.hh/.cc`, `deg_builder_nodes.cc` (+include `BKE_pegrig.hh`,
  `get_cow_datablock`), `deg_builder_relations.cc`, `constraint.cc`.
  **Validado numericamente headless** (delta de pose, herança de pai, múltiplos consumidores = PASS;
  teste em `scratchpad/e1_validate.py`).
- **E7** Curve: tabela de 256 amostras 1×/avaliação (não por-drawing). `MOD_grease_pencil_curve.cc`.
- **E8** Cutter: `find_fill_material_index` içado pra fora do loop. `MOD_grease_pencil_mask.cc`.
- **E9** Contour: scratch de deformação por-thread (EnumerableThreadSpecific). `MOD_grease_pencil_contour.cc`.
- **Python (`nuclear_peg_graph.py`):** overlay cacheia conjunto-controlado + hull (por frame/mw/view) +
  memoiza matrizes de peg; handler de depsgraph com **debounce ~250ms**; badge do nó cacheado;
  Auto-Rig usa índice de `pegs.new()` (O(peças²)→O(peças)); gizmo de curva `_bp()` com bounds-check.

### 4. Builds e verificação
- Build incremental `-j2` no container distrobox **`blender`**, dir **`~/Documentos/GitHub/build_nuclear_full`**.
  Limite de RAM via `systemd-run --scope MemoryHigh=6G` + `nice -19` (máquina divide RAM com Blenders do DPE).
- Smoke tests headless OK (módulos carregam, 3 modifiers GP avaliam sem crash, reset ops registrados).
- E1 validado numericamente (ver acima).

### 5. Empacotamento do release (pronto, não publicado)
- Versão já bumpada → release **`--no-bump`**, sem rebuild.
- **Bloqueador resolvido:** o full rebuild zerou o `scipy` do `site-packages` (regra de ouro nº4);
  copiado de `bin/versions/1.3.1-b5` (scipy 1.17.1, idêntico à produção) e **import testado**.
  ⚠️ Confirmado que o zip de produção b7 só empacota `scipy` (a lista longa da regra de ouro está
  desatualizada; o `verify-zip` só checa scipy).
- Staging limpo (excluídos os ~5GB de `bin/versions/` + `bin/current`, relíquias de auto-update desta máquina).
- **Artefatos prontos em `~/Documentos/GitHub/build_nuclear_full/`:**
  - `nuclear.zip` — 618 MB (**647.204.503 bytes**), sha256 **`fc58f5a31d52281b9bba85a65eb8c7e83e587fcef4d7ee09f6d378a6396d310a`**
  - `version.json` — build 8, 1.4.3 (Beta), com notes
  - **verify-zip OK** (updater + scipy), **check-manifest OK** (sha256/size batem).

---

## ⛔ O que falta — BLOQUEADOR: regressão do squash em peg rotacionada

### Sintoma (achado no teste ao vivo)
"O rig se move no eixo X ao usar o squash." Peças **deslizam em X** ao squashar uma peg
**rotacionada/posada** (membro). Peg **sem rotação** funciona certo.

### Causa-raiz (confirmada pela leitura do código)
A reescrita XZ do squash (veio no merge, **nova na 1.4.3** — a produção b7 tinha o squash antigo eixo-Y)
assume que o vertical do desenho é o **eixo Z LOCAL da peg**:
- O enable (`object_pegrig.cc`) mapeia o vertical do mundo (Z) pro local via `invert(peg_world)`.
  Numa peg rotacionada, isso vira um vetor **inclinado** no espaço local.
- O gizmo (`nuclear_squash_gizmo.py`, `_make_set`/TIP, ~linha 164) **trava o tip diretamente acima do
  anchor em local** (`peg.squash_tip = (anchor[0], 0.0, local.z)`) — o eixo de squash é SEMPRE o Z local.
- O driver (`pegrig.cc` `pegrig_peg_local_matrix`, ~linhas 298-314) escala `local-Z` por `s` e
  `local-X` por `k` com compensação `squash[3][0] = anchor.x*(1-k)`.

Como o eixo de escala (Z local) **não acompanha o vertical real do desenho** numa peg rotacionada,
a escala tem componente em X-mundo → a peça **escorrega lateralmente**. O meu fix de `rest_len` NÃO é
a causa (ele só removeu o "pulo" em repouso, e está correto); a causa é o modelo de escala XZ.

### Conserto proposto (opção (a), escolhida pelo usuário)
Fazer o squash escalar ao longo da **direção real anchor→tip** (o vertical do desenho no frame local),
não do Z local fixo. Precisa ser consistente em 3 lugares:
1. **Driver** (`pegrig.cc`): construir a escala 2D no plano XZ ao longo do eixo `a = normalize(tip-anchor)_xz`
   por `s` e perpendicular por `k`, ancorada em `anchor` (matriz `M = s·aaᵀ + k·ppᵀ` no XZ, com
   translação `anchor - M·anchor`; Y intocado).
2. **`rest_len`** (`object_pegrig.cc`): passar a ser o comprimento XZ de `tip-anchor` (não só o delta-Z),
   pra `s = |tip-anchor|_xz / rest_len` dar 1 em repouso.
3. **Gizmo** (`nuclear_squash_gizmo.py`): NÃO travar mais o tip "acima do anchor em local"
   (`_make_set`/TIP, ~linha 161-165) — deixar o tip livre no plano XZ pra o eixo poder seguir o
   vertical real do desenho; ajustar o overlay `_draw_squash_axis` (~linha 224) de acordo.

Depois: **rebuild** (`-j2` no container `blender`, dir `build_nuclear_full`) + **re-teste ao vivo**
(squashar peg rotacionada NÃO pode deslizar; peg sem rotação continua certo) + atualizar este doc.

### Alternativa descartada nesta sessão
Opção (b): publicar a 1.4.3 sem a reescrita XZ do squash (revertendo só o squash, mantendo o resto).
O usuário escolheu (a) — corrigir o squash.

---

## Passos restantes do release (depois do fix do squash)

1. **Corrigir o squash** (3 arquivos acima) + rebuild + re-teste ao vivo.
2. **Re-empacotar** (o sha256 muda): garantir scipy presente no `site-packages`, staging limpo,
   `verify-zip` + `check-manifest`.
3. **Publicar** (precisa de OK explícito — é irreversível, máquinas auto-atualizam):
   ```sh
   # backup do b7 atual
   ssh araga286 'cp ~/public_html/addon/rapaduraatomica/estacao/nuclear.zip \
                     ~/public_html/addon/rapaduraatomica/estacao/nuclear.zip.bak-pre-1.4.3'
   # subir zip + manifesto JUNTOS (regra de ouro nº2)
   scp ~/Documentos/GitHub/build_nuclear_full/nuclear.zip \
       ~/Documentos/GitHub/build_nuclear_full/version.json \
       araga286:~/public_html/addon/rapaduraatomica/estacao/
   # conferir no servidor
   ssh araga286 'sha256sum .../estacao/nuclear.zip && stat -c %s .../estacao/nuclear.zip'
   ```
4. **Pós-publish:** atualizar o espelho `tools/nuclear_telemetry/server/version.json`, a seção
   "Estado atual" de `tools/nuclear_claude/CLAUDE.md`, e fazer o commit final.

---

## Itens NÃO consertados (de propósito — pré-existentes/arquiteturais, não regressões)
- MVC do Contour recomputado sem cache de pesos (fix real = bakear no Bind).
- Bank-frames a 100000 dobram a contagem de drawings (custo linear no copy-on-eval do GP).
- Reset da curve após subdividir restaura só os N pontos antigos (borda, silencioso).
- Keymap de reset ambíguo quando um GP tem modifier Curve **e** Contour (UX).

---

## Referência rápida
- **Branch:** `integration/1.4.3-audit` (commits: `580d349`, `d5766be`, `068557a`, `9890762`, `c9cd016`).
- **Build dir:** `~/Documentos/GitHub/build_nuclear_full` (container distrobox `blender`).
- **Binário:** `build_nuclear_full/bin/blender` (reporta "Nuclear 1.4.3 (Beta)").
- **Produção:** 1.4.2 / build 7 (sha256 `a851b665…`).
- **Fluxo de release:** `tools/nuclear_claude/CLAUDE.md` §5 (regras de ouro nº1-4).
