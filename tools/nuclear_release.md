# Como fazer um release do Nuclear sozinho

> Guia rápido pra devs. A fonte da verdade do sistema de auto-update (modelo de versão,
> formato do manifesto, restrições de deploy) é
> [`tools/nuclear_claude/CLAUDE.md`](nuclear_claude/CLAUDE.md) (seção "Nuclear — sistema
> de atualização"). Este arquivo é só o "como usar a ferramenta".

## TL;DR

```sh
cd ~/Documentos/GitHub/Nuclear
tools/nuclear_release.sh patch --build --notes "corrigiu o crash X"
```

Isso faz tudo: bump de versão → build → empacotar → verificar → gerar manifesto →
perguntar antes de publicar → lembrar de atualizar o CLAUDE.md → perguntar antes de
comitar.

## O modelo de versão, em uma frase

Tem dois números: `MAJOR.MINOR.PATCH` (cosmético, semver) e `NUCLEAR_BUILD` (o que o
updater realmente compara). Toda release incrementa os dois — o script cuida disso
sozinho, você só escolhe `patch`/`minor`/`major`.

## `tools/nuclear_release.sh` — o atalho completo

```sh
tools/nuclear_release.sh <patch|minor|major> [opções]
tools/nuclear_release.sh --no-bump [opções]   # se a versão já foi ajustada na mão
```

### Quando usar cada tipo de bump

| Tipo | Exemplo | Quando |
|---|---|---|
| `patch` | 1.1.0 → 1.1.1 | correção de bug, sem recurso novo |
| `minor` | 1.1.0 → 1.2.0 | recurso novo, compatível |
| `major` | 1.1.0 → 2.0.0 | mudança grande / quebra compatibilidade |

### Flags

| Flag | Efeito |
|---|---|
| `--build` | Compila via `distrobox enter blenderdev` antes de empacotar. **Sem essa flag o build é pulado** — o script assume que `bin/` já está atualizado. |
| `--dry-run` | Só imprime os comandos, não executa nada. Roda primeiro com isso se não tiver certeza. |
| `--notes "texto"` | Notas de release pro manifesto. Se omitir, o script pergunta. |
| `--no-bump` | Pula o bump (use se já editou `BKE_blender_version.h` na mão). |
| `--build-dir DIR` | Diretório de build (padrão: `../build_nuclear_full`, irmão do repo). |
| `--remote host:path` | Destino do `scp` (padrão: `estacao/` em produção). |
| `--yes` / `-y` | Responde "sim" a toda confirmação sem perguntar. Use com cuidado — pula inclusive a confirmação de build e de publish. |
| `-h` / `--help` | Mostra o resumo de uso. |

### O que cada etapa faz (e quando ela pergunta antes de agir)

1. **Bump** — roda direto.
2. **Build** — só roda com `--build`; aí confirma antes (é lento, ~20min, e pode colidir
   com outro build).
3. **Empacotar** — recria `Nuclear/` no build dir (`cp -al bin Nuclear`), carimba
   (`nuclear_version.json`) e gera o zip. Roda direto.
4. **Verificar** — roda `verify-zip` (updater + deps Python embutidos) e `check-manifest`
   (sha256/size) automaticamente. **Se algo estiver errado, o script para aqui** — nada é
   publicado quebrado.
5. **Publicar** — confirma antes do `scp` pro servidor (a etapa mais difícil de desfazer).
   Sempre sobe `nuclear.zip` **e** `version.json` juntos.
6. **Lembrete do CLAUDE.md** — imprime um bloco pra você colar na seção "Estado atual" de
   `tools/nuclear_claude/CLAUDE.md`. O script **não edita esse arquivo por você** — a
   prosa de "o que mudou" fica com quem está fazendo o release.
7. **Commit** — confirma antes; se você disser sim, pede a mensagem.

O que o script **nunca** faz: tocar em `ping.php` ou `instalarNuclear.sh` em produção.
Esses deploys de código continuam exigindo aprovação manual, fora do script.

### Exemplos

```sh
# Ver o que aconteceria, sem rodar nada de verdade
tools/nuclear_release.sh minor --dry-run

# Já buildou e empacotou na mão, só falta manifesto/publish/commit
tools/nuclear_release.sh --no-bump --notes "rebuild com fix do crash"

# Build dir diferente do padrão
tools/nuclear_release.sh patch --build --build-dir ~/builds/nuclear_lite --notes "..."
```

## Os subcomandos soltos (`nuclear_release.py`)

Se preferir montar o fluxo na mão em vez de usar o `.sh`:

```sh
python tools/nuclear_release.py bump {patch|minor|major}
python tools/nuclear_release.py version                      # sanity check
python tools/nuclear_release.py stamp <pasta-do-build>        # grava nuclear_version.json
python tools/nuclear_release.py verify-zip --zip nuclear.zip  # regras de ouro #3/#4
python tools/nuclear_release.py manifest --zip nuclear.zip --notes "..." -o version.json
python tools/nuclear_release.py check-manifest --zip nuclear.zip --manifest version.json
```

Todos aceitam `--header <path>` pra apontar pra um `BKE_blender_version.h` diferente do
repo atual (útil em testes).

## Resolvendo "checksum não confere"

Quase sempre é o zip que mudou e o manifesto que ficou velho. Se tiver os dois arquivos
localmente:

```sh
python tools/nuclear_release.py check-manifest --zip nuclear.zip --manifest version.json
```

Ele diz exatamente o que diverge (sha256 e/ou size). Recalcule, atualize o
`version.json` (repo e servidor) e não precisa rebuild nem bump se a versão não mudou.

## Onde isso é publicado

`ssh araga286` (HostGator) → `~/public_html/addon/rapaduraatomica/estacao/`:
- `version.json` — o manifesto que o updater lê.
- `nuclear.zip` — o build portátil.

Esses dois são dados, não código — atualizá-los via `scp` é permitido. `ping.php` e
`instalarNuclear.sh` são código em produção e exigem aprovação manual a cada deploy.

## Ver também

- [`tools/nuclear_claude/CLAUDE.md`](nuclear_claude/CLAUDE.md) — fonte da verdade do
  sistema de auto-update (modelo de versão completo, formato do `version.json`,
  troubleshooting, estado atual).
- [`.claude/agents/nuclear-release.md`](../.claude/agents/nuclear-release.md) — o agente
  Claude que faz a mesma coisa, se preferir pedir pra ele em vez de rodar você mesmo.
