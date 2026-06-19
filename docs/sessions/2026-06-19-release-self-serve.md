# Session: Release self-serve para programadores

**Date**: 2026-06-19
**Tier**: 2 — Light
**Specialist**: devops

## Task
Ler `.claude/agents/nuclear-release.md` e criar uma forma mais fácil dos programadores
rodarem o fluxo de release do Nuclear por conta própria, sem precisar do agente Claude.

## What Was Done
- Adicionados três subcomandos a `tools/nuclear_release.py`: `bump {patch|minor|major}`
  (edita `BKE_blender_version.h` com segurança e sempre soma +1 em `NUCLEAR_BUILD`),
  `verify-zip --zip Z` (checa as regras de ouro #3/#4 via `zipfile`, sem depender de
  `unzip` externo) e `check-manifest --zip Z --manifest version.json` (recalcula
  sha256/size e resolve "checksum não confere" com um comando só).
- Criado `tools/nuclear_release.sh`, um orquestrador bash que encadeia bump → rebuild
  opcional (só com `--build` explícito) → empacotar (`cp -al`/`stamp`/`zip`) → as duas
  verificações automáticas → publicar (scp do zip+manifesto juntos, com confirmação) →
  bloco-lembrete para colar no CLAUDE.md → commit opcional (sem `Co-Authored-By`, é um
  humano rodando). Tem `--dry-run` e nunca toca `ping.php`/`instalarNuclear.sh`.
- Corrigido o nome do container distrobox (`blender` → `blenderdev`, o real) em
  `.claude/agents/nuclear-release.md` e `tools/nuclear_claude/CLAUDE.md`.
- Documentada a nova rota em `tools/nuclear_claude/CLAUDE.md` §5 ("Atalho: rodar o
  release sozinho") e referenciada de volta no próprio agente, para que humano e agente
  compartilhem o mesmo fluxo.

## Decisions Made
- A lógica pesada (parsing do header, sha256, manifesto) ficou em Python
  (`nuclear_release.py`, já sem dependências externas) e só a orquestração/glue
  (distrobox, scp, git, prompts de confirmação) ficou em bash — evita reimplementar
  parsing de regex em shell e mantém uma única fonte de verdade testável.
- `--build` é uma flag explícita, não o padrão: preserva a regra original de "confirme
  antes de buildar" (build é lento e pode colidir com outro processo), só que agora a
  confirmação é o próprio humano passando a flag, não uma pergunta ao agente.
- O script nunca edita o CLAUDE.md automaticamente — só imprime o bloco pronto pra colar.
  A prosa de "o que mudou" exige julgamento humano e não deveria ser sintetizada às
  pressas por um script.
- `verify-zip`/`check-manifest` ganharam testes manuais com zips sintéticos (bom e
  "quebrado") em vez de empacotar o build real (~660MB) — mais rápido e sem side effects
  no `build_nuclear_full/` ou no servidor.

## Modified Files
- `tools/nuclear_release.py` — subcomandos `bump`, `verify-zip`, `check-manifest` novos.
- `tools/nuclear_release.sh` — novo, orquestrador self-serve.
- `.claude/agents/nuclear-release.md` — referencia os subcomandos novos, corrige
  `blenderdev`, aponta para o script self-serve.
- `tools/nuclear_claude/CLAUDE.md` — corrige `blenderdev`, nova subseção "Atalho: rodar o
  release sozinho".
- `docs/CHANGELOG.md` — entrada em `[Unreleased] / Added`.
