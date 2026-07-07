# ADR: Modelo comercial híbrido (GPL-pago + componentes out-of-process)

- **Data:** 2026-07-07
- **Status:** aceito (decisão do israel, sessão de refatoração da demanda #6)
- **Contexto relacionado:** `TRADEMARK.md`, `build_files/cmake/config/nuclear_2d.cmake`,
  ADR 2026-06-23 (merge Auto-Patch + Envelope), relatório `~/relatorios/demanda-6.md`

## Contexto

O Nuclear é um fork do Blender 5.0 e, portanto, **GPL-2.0-or-later de forma
irrevogável** — não existe caminho jurídico para fechar o core ou "sair" da GPL.
O objetivo do projeto é ser rentável via **suporte, addons e melhorias**, mantendo
licença e atribuição intactas.

A GPL não impede lucro; ela impede *restringir a redistribuição do código*. As
alavancas de monetização compatíveis são conhecidas e testadas no ecossistema
Blender (Blender Market, Store da própria Blender Foundation, studios de serviço).

Ponto jurídico central: a posição da Blender Foundation é que **addons Python que
importam `bpy` são obras derivadas** e, portanto, GPL. Já um **executável separado**
que conversa com o Nuclear por IPC/arquivos/rede **não é derivado** e pode ter
qualquer licença.

## Decisão

Adotar um modelo **híbrido**, com três trilhas de receita:

1. **Addons GPL vendendo acesso** (modelo Blender Market): o código do addon é GPL,
   mas o *download, as atualizações e o suporte* são pagos. Aplicável aos addons
   Python in-process (que importam `bpy`). O comprador pode redistribuir o código;
   na prática o valor está no canal oficial de updates + suporte.
2. **Componentes out-of-process proprietários**: features de alto valor (ex.: motor
   de IA do Entremeio) vivem em **executável separado**, licença proprietária,
   comunicando com o Nuclear via IPC/arquivos. Dentro do Nuclear fica só uma
   **ponte fina GPL** (operadores/painéis que disparam o processo externo e leem o
   resultado), sem lógica de valor embutida.
3. **Serviços**: suporte comercial, treinamento, customização sob contrato e
   assets (templates, brushes, bibliotecas de células) — fora do escopo da GPL.

A **marca "Nuclear"** (não coberta pela GPL) protege a distribuição oficial:
qualquer um pode forkar o código, ninguém pode distribuir sob o nome/logo Nuclear
(ver `TRADEMARK.md`).

## Regras de arquitetura (obrigatórias)

- Código pago-proprietário **NUNCA** importa `bpy`, nunca linka com o binário do
  Nuclear e nunca é carregado no processo do Nuclear. Comunicação exclusivamente
  via subprocess/socket/arquivos.
- A ponte GPL dentro do Nuclear deve ser **fina e genérica**: serializa entrada,
  chama o processo externo, desserializa saída. Se a ponte "sabe demais", o valor
  vazou para a GPL.
- Todo addon in-process é GPL desde o primeiro commit (header SPDX), mesmo os
  vendidos — sem exceção, sem "dual license" ilusório.
- O repositório público do fork permanece completo e compilável (GPL cumprida
  na íntegra); o que é pago vive em repositórios separados.

## Consequências

- **Positivas:** risco jurídico zero; compatível com o ecossistema Blender; a
  infraestrutura já existente (servidor de update, telemetria, instalador) vira o
  canal de entrega do que é pago; o Entremeio já nasceu na arquitetura certa (IPC).
- **Negativas/custos:** features pagas de alto valor exigem mais engenharia
  (processo externo + ponte); addons GPL-pagos podem ser redistribuídos de graça
  (mitigado pelo canal de updates/suporte); a marca precisa ser registrada no INPI
  para ter força plena (pendência administrativa, não técnica).

## Notas de build (mesma sessão)

O preset `nuclear_2d.cmake` (demanda #6, −21% de binário) + aceleradores
(ccache/mold) foram promovidos do laboratório `nuclear2d` para este repositório e
passam a ser a base das releases oficiais — binário e zip menores baixam mais
rápido no auto-update e compilam mais rápido a cada release (custo por release cai,
margem de suporte sobe).
