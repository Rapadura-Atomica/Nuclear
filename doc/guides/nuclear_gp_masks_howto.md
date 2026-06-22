# Nuclear — Masks de GP na prática (criar e manipular do zero)

Guia passo-a-passo de uso. Para a parte técnica/arquitetura, veja
[`nuclear_gp_masks.md`](nuclear_gp_masks.md).

Três coisas que dá pra fazer:

- **Mask dentro do mesmo objeto** — uma layer corta outra (já existe no Blender).
- **Mask de peg/grupo** — mascarar um grupo/peg inteiro (todas as folhas dele).
- **Cutter cross-object** — um *outro objeto* GP serve de matte (estilo Toon Boom Cutter).

> ⚠️ **Regra de ouro:** máscara é *opt-in por layer*. Em **Object Data Properties ▸ Layers ▸
> Masks**, ligue o **Use Masks** (a caixinha no cabeçalho do painel). Sem isso, nada corta.

---

## Caminho A — Cutter cross-object pelo painel (do zero)

1. **Add ▸ Grease Pencil ▸ Monkey** duas vezes. Mova uma no eixo X pra elas se sobreporem em
   parte. Renomeie: `Matte` (a que vai cortar) e `Masked` (a que será cortada).
2. Selecione **`Masked`** → **Object Data Properties** (ícone de folha) → painel **Layers** →
   subpainel **Masks**.
3. Ligue o **Use Masks** (caixinha no cabeçalho do painel Masks).
4. Clique no **+** pra adicionar uma entrada de máscara.
5. Na linha da máscara, no campo **objeto** (ícone de objeto), escolha **`Matte`**. Deixe o
   **nome vazio** = objeto inteiro.
6. Pronto: a `Masked` aparece só onde a `Matte` a cobre. Mova a `Matte` (G) → o corte segue.

---

## Caminho B — Mask dentro do mesmo objeto

1. Num objeto GP com 2+ layers (ex.: `linha` e `recorte`).
2. Selecione a layer que será cortada → painel **Masks** → **Use Masks** ☑.
3. **+** ▸ escolha a outra layer pelo nome (o menu lista as layers do objeto). Deixe o campo
   **objeto** vazio (mesmo objeto).

---

## Caminho C — Mask numa peg/grupo (corta o grupo inteiro)

1. No painel **Layers**, crie um **grupo** (botão de nova pasta), arraste layers pra dentro e,
   se quiser, marque-o como **Peg** (no painel do grupo).
2. Coloque a máscara **no grupo** (via script/Peg View hoje; pela UI, ponha em cada folha ou
   use o grupo como *alvo* da máscara de outra layer).
3. Toda folha sob o grupo herda a máscara. Uma máscara que aponta para um grupo expande para
   todas as folhas dele.

---

## Caminho D — Pela Peg View (criar e ligar do zero)

A Peg View é um Node Editor que mostra a rig de pegs e os drawings.

1. **Montar a rig:** selecione os drawings → num Node Editor, troque o tipo de árvore para
   **Peg Graph** → painel lateral (N) ▸ aba **Peg** ▸ **Sync**. Se ainda não há rig, use
   **Add Peg** e **Bind Selected Drawings** pra vincular os objetos.
2. Cada **Drawing node** tem dois sockets cianos: **Matte Out** e **Matte In**.
3. **Criar o corte:** arraste de **`Matte` ▸ Matte Out** até **`Masked` ▸ Matte In**. Isso
   grava o cutter de objeto inteiro em `Masked` e **liga o Use Masks** automaticamente.
4. **Remover:** apague o link → a máscara some e a `Masked` volta inteira.

O fluxo é bidirecional: criar/remover pelo painel reflete na Peg View no próximo Sync, e
vice-versa.

---

## Inverter e remover

- **Inverter** (mostrar onde o matte *não* está): na linha da máscara (painel Masks), clique no
  ícone de inverter.
- **Remover:** botão **−** no painel, ou apague o link na Peg View.

## Limitações (v1)

- O objeto-**matte precisa estar visível** no view layer; se escondê-lo (H), o corte vira uma
  silhueta vazia.
- O bitmap de máscara same-object é limitado a **256 layers** por objeto.
- O link da Peg View cria sempre um cutter de **objeto inteiro**; matte por layer/grupo
  específico é pelo painel (campo objeto + nome do nó).
</content>
