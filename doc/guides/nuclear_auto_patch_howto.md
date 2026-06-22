# Auto-Patch GP — como montar do zero (guia do rigger)

> **Para quem:** quem está rigando/montando cutout 2D em Grease Pencil v3 (Blender 5.0 / fork
> Nuclear) e quer sumir com a **linha dupla** nas juntas (estilo Auto Patch do Toon Boom Harmony).
>
> **O que o auto-patch faz:** corta **só a LINHA** da peça de baixo onde a peça de cima (occluder)
> sobrepõe, **mantendo o fill**. Não corta fill — isso é de propósito (evita buracos quando as
> peças se movem).
>
> Mecânica/engine e estado de implementação: ver
> [`nuclear_auto_patch_harmony_fidelity.md`](nuclear_auto_patch_harmony_fidelity.md).

---

## 1. Pré-requisitos das peças

- **Duas peças GP como objetos separados**: a peça a remendar + o occluder (a que fica por cima).
- **Occluder com fill OPACO e fechado** (alpha = 1). Fill semi-transparente → matte fraco → **não
  corta** (a força do corte = opacidade do fill do occluder).
- As peças precisam **se sobrepor** na junta (sem sobreposição não há linha dupla pra cortar; em
  pose de descanso, dobre a junta).
- O occluder deve desenhar **na frente** (ordem de desenho, ou "In Front").

---

## 2. Passo a passo (interface)

### Passo 1 — Ache a camada que TEM a linha ⚠️ (a pegadinha nº 1)
O operador atua na **camada ATIVA**. **Os nomes das camadas mentem** — não confie em "Lines".
(Caso real: no `JulianoHeroiAtualização.blend` a camada `Lines` estava **vazia**; a arte —
linha + fill — estava toda na camada `Color`. Mascarar `Lines` dava efeito **zero**.)

- Selecione a peça a remendar → *Object Data Properties* (ícone verde de GP) → painel **Layers**.
- Descubra qual camada contém o **contorno preto** (desligue o olho das outras; a que faz a linha
  sumir é a certa). Deixe **essa** como **ativa**.

### Passo 2 — Selecione na ordem certa
- Clique primeiro no **occluder** (peça de cima).
- **Shift+clique** na peça a remendar → ela vira a **ativa** (contorno mais claro).
- Regra: **ativo = remendado; outro selecionado = occluder.**

### Passo 3 — Rode o operador
- *Object Data Properties → Layers →* subpainel **Masks** → botão **"Auto Patch"** (ícone de
  máscara). É o operador `grease_pencil.auto_patch`.

### Passo 4 — Ajuste no painel de redo (canto inferior esquerdo)
- **Matte Source = Occluder** (normal). `Self` = junta interna de uma peça só (matte = outra
  camada do próprio objeto) — funciona com ressalvas; ver doc de fidelidade.
- **Mutual** ✓ → cria também a máscara **recíproca** no occluder, limpando os **dois lados** da
  junta de uma vez.

### Passo 5 — Ordem de desenho
- Occluder **na frente** (ou ligue "In Front" em *Object Properties → Visibility*). Se as duas
  peças ficarem no **mesmo Z**, o operador emite um aviso ("same depth; draw order is undefined") —
  dê um Z diferente ou ligue In Front.

---

## 3. O que o operador cria

Uma `LayerMask` na camada ativa com:
- `object` = occluder;
- flags **`invert` + `auto_patch`**;
- "Use Masks" ligado.

Com `mutual`, cria a recíproca no occluder (alvo = a camada de mesmo nome, fallback = camada ativa
do occluder).

---

## 4. Como conferir

- Vista **Rendered**, com sobreposição real na junta.
- Selecione a peça remendada → camada (a de arte) → alterne **"Use Masks"**: a linha dupla na
  junta **some/volta**.
- ⚠️ Com **occluder opaco na frente**, ON e OFF parecem **idênticos** — é **oclusão** (ele cobre o
  corte), **não é bug**. O ganho fica visível na **costura** e no **movimento/pose**. Para ver o
  corte isolado num teste, ponha o occluder **atrás** e olhe a linha da peça de cima sendo cortada.

---

## 5. As pegadinhas que mais derrubam

| # | Sintoma | Causa | Correção |
|---|---|---|---|
| 1 | Efeito **zero** | mascarou a camada **errada** (vazia) | mascare a camada que **tem a linha** (cheque por conteúdo, não pelo nome) |
| 2 | Não corta | fill do **occluder semi-transparente** | fill do occluder **opaco** (alpha 1) |
| 3 | Nada acontece | **sem sobreposição** ou peças **coplanares** | crie overlap (dobre a junta) / dê Z diferente ou "In Front" |
| 4 | ON = OFF idêntico (opaco/frente) | **oclusão** (esperado) | olhe a costura/movimento, ou teste com occluder atrás |

---

## 6. Validação empírica (referência)

Medições por amostragem de pixel (processo fresco, build com o depth-fix `e3a4f264bf2`):

- **Cena sintética, linha+fill na MESMA camada:** corte de ~10.135 px (36%) na zona do occluder,
  com as duas peças **visíveis**.
- **Cena sintética, linha e fill em CAMADAS SEPARADAS** (estilo Harmony): corte de ~6.835 px (39%)
  na camada `Line`, fill da camada `Fill` intacto.
- **Personagem real (Juliano, cotovelo), arte na camada `Color`:** corte de ~4.097 px — **depois**
  de apontar o auto-patch para a camada que de fato contém a linha (a `Lines` do rig era vazia).

Conclusão: o auto-patch funciona com linha/fill **na mesma** camada ou **separados**; o que decide
é mascarar a camada que **contém a linha**.

---

## 7. Melhoria sugerida (UX)

Como o nome da camada não é confiável, o operador poderia **avisar quando a camada ativa estiver
vazia** (sem strokes) — evitaria a pegadinha nº 1. Candidato a follow-up no operador
`grease_pencil.auto_patch`.

---

## 8. Referências

- [`nuclear_auto_patch_harmony_fidelity.md`](nuclear_auto_patch_harmony_fidelity.md) — mecânica do engine, status A–D + mutual + depth-fix.
- [`nuclear_auto_patch_bc_followup.md`](nuclear_auto_patch_bc_followup.md) — diagnóstico/resolução do bug B/C.
- [`nuclear_auto_patch_validation_b_2026-06-18.md`](nuclear_auto_patch_validation_b_2026-06-18.md) — validação por pixel + lição de método (vista TOP, processo fresco).
- [`nuclear_gp_masks_howto.md`](nuclear_gp_masks_howto.md) — masks GP em geral.
