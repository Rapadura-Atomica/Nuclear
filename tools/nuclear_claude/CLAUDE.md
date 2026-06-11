<!-- SPDX-FileCopyrightText: 2026 Blender Authors -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Nuclear — sistema de atualização (documentação viva)

> **Este arquivo é a fonte da verdade do sistema de auto-update do Nuclear.**
> Sempre que QUALQUER peça mudar (versão, fluxo, caminho de servidor, formato do
> `version.json`, etc.), **atualize este documento na mesma leva**. O agente
> `nuclear-release` é obrigado a fazer isso ao final de cada release.

Última atualização: 2026-06-11.

---

## 1. Visão geral

O Nuclear (fork do Blender) tem um atualizador embutido. Ao abrir, ele consulta um
manifesto JSON no servidor, compara com a versão que está rodando e, se houver build
mais novo, mostra uma tela fixa (estilo "Sobre"). O usuário clica e o próprio Nuclear
baixa, verifica o checksum, troca a versão e reinicia. Tudo no `$HOME` — funciona em SO
imutável (Bazzite/Fedora Atomic) sem mexer em `/usr`, sem fork, sem git, sem recompilar.

Prioridade: **Linux (Bazzite)**. Windows é suportado no apply (junction), mas não testado
em máquina real. macOS cai no fallback de abrir a página.

## 2. Modelo de versão — LEIA ANTES DE MEXER

Há **dois** números, com papéis diferentes:

| Campo | Para quê | Regra |
| --- | --- | --- |
| `NUCLEAR_BUILD` (inteiro) | **Comparação** "tem update?" | **SEMPRE +1 a cada release.** Monotônico. É o que o updater compara. |
| `MAJOR.MINOR.PATCH` (ex: 1.1.0) | **Cosmético** (o que o humano vê) | Segue semver. Não é usado na comparação. |

**Esquema semver (a "questão 1.0.1 / 1.1 / 1.2"):**
- **PATCH** (`1.0.0 → 1.0.1`): correção de bug, sem recurso novo.
- **MINOR** (`1.0.0 → 1.1.0`): recurso novo, compatível.
- **MAJOR** (`1.0.0 → 2.0.0`): mudança grande/quebra de compatibilidade.

> ⚠️ Regra de ouro nº1: **toda release incrementa `NUCLEAR_BUILD`**, não importa se foi
> patch, minor ou major. Se esquecer, as máquinas não enxergam o update (build não é
> maior que o instalado).

Fonte única da verdade: as defines em
`source/blender/blenkernel/BKE_blender_version.h`:

```c
#define NUCLEAR_VERSION_MAJOR 1
#define NUCLEAR_VERSION_MINOR 0
#define NUCLEAR_VERSION_PATCH 0
#define NUCLEAR_BUILD         1
#define NUCLEAR_VERSION_STAGE "Beta"
```

`NUCLEAR_VERSION_STRING` ("Nuclear 1.0.0 (Beta)", na barra de título) é **derivado**
dessas defines. Edite os números aqui e em mais lugar nenhum.

## 3. Peças e arquivos

**No repositório:**
| Caminho | O quê |
| --- | --- |
| `source/blender/blenkernel/BKE_blender_version.h` | defines de versão (fonte única) |
| `scripts/startup/nuclear_update.py` | cliente embutido (notifica + baixa + aplica) |
| `tools/nuclear_release.py` | gera `nuclear_version.json` e `version.json` a partir das defines |
| `tools/nuclear_install/instalarNuclear.sh` | instalador (layout versionado + symlink + .desktop) |
| `tools/nuclear_telemetry/server/version.json` | espelho do manifesto (referência) |
| `tools/nuclear_telemetry/server/ping.php` | espelho do endpoint de telemetria (eco do manifesto) |
| `tools/nuclear_claude/CLAUDE.md` | **este arquivo** |

**No servidor** (HostGator, `ssh araga286`; domínio `rapaduraatomica.com.br` →
`~/public_html/addon/rapaduraatomica/`):
| URL | Arquivo no disco | O quê |
| --- | --- | --- |
| `estacao/version.json` | `…/estacao/version.json` | **o manifesto que o updater lê** |
| `estacao/nuclear.zip` | `…/estacao/nuclear.zip` | o build portátil (topo `Nuclear/<ver>/…`) |
| `estacao/addons.zip` | `…/estacao/addons.zip` | addons externos |
| `nuclear/nuclear-api/ping.php` | idem | telemetria de presença |

## 4. Formato do `version.json`

```json
{
  "name": "Nuclear",
  "build": 1,
  "version": "1.0.0",
  "stage": "Beta",
  "version_string": "Nuclear 1.0.0 (Beta)",
  "url": "https://rapaduraatomica.com.br/estacao/nuclear.zip",
  "sha256": "<sha256 do nuclear.zip ATUAL>",
  "size": 728581557,
  "min_build": 0,
  "notes_url": "https://github.com/Rapadura-Atomica/Nuclear/releases",
  "notes": "texto curto do que mudou"
}
```

O cliente compara `build` com o build instalado (lido de `nuclear_version.json`, que fica
ao lado do binário). `sha256`/`size` precisam casar **exatamente** com o zip servido.

## 5. Fluxo de release (a sequência correta)

> ⚠️ Regra de ouro nº2: **`nuclear.zip` e `version.json` andam SEMPRE em par.** Nunca suba
> um sem o outro. Foi o que causou o erro "checksum não confere" em 2026-06-11: o zip foi
> trocado e o manifesto ficou com o hash velho.

1. **Bump de versão** em `BKE_blender_version.h`: ajuste MAJOR/MINOR/PATCH conforme o tipo
   de mudança e **incremente `NUCLEAR_BUILD`**.
2. **Rebuild** do Nuclear (externo — o agente não compila; ~40min; cuidado com builds
   concorrentes em outros processos).
3. **Carimbar** o build: `python tools/nuclear_release.py stamp <pasta-do-build>`
   → grava `nuclear_version.json` ao lado do binário.
4. **Empacotar** o zip portátil (topo `Nuclear/<ver>/…`).
5. **Gerar o manifesto** do zip empacotado:
   ```sh
   python tools/nuclear_release.py manifest --zip <nuclear.zip> \
     --notes "o que mudou" -o version.json
   ```
6. **Subir os dois juntos** pra `estacao/`: `nuclear.zip` **e** `version.json`.
7. **Atualizar ESTE CLAUDE.md** (a tabela de versão atual, a data, o que mudou).
8. **Commit** das mudanças do repo (header, version.json espelho, este doc).

### Atalho: só corrigir o manifesto de um zip que já está no servidor
Se o zip mudou mas a versão não, recalcule e regrave só o manifesto:
```sh
ssh araga286 'sha256sum ~/public_html/addon/rapaduraatomica/estacao/nuclear.zip; \
              stat -c %s ~/public_html/addon/rapaduraatomica/estacao/nuclear.zip'
# edite sha256 + size no version.json e suba só ele
```

## 6. Restrições de deploy (IMPORTANTE)

- O classificador de segurança do Claude Code **bloqueia sobrescrever CÓDIGO em produção**
  (ex.: `ping.php`, `instalarNuclear.sh`). Esses deploys precisam de **aprovação explícita
  do usuário** a cada vez. Faça backup antes.
- **Adicionar/atualizar arquivos de dados** que nós criamos (ex.: `version.json`) é
  permitido — foi assim que o manifesto foi publicado e corrigido.
- Token compartilhado da telemetria (header `X-Nuclear-Token`) já está no repo/servidor.

## 7. Layout de instalação (apply)

Esquema versionado com symlink atômico (Linux) / junction (Windows):
```
~/Nuclear/
  versions/<versão>-b<build>/   <- pasta portátil completa
  current -> versions/<...>      <- ponteiro; o .desktop lança ESTE
```
Apply = baixar → verificar sha256 → extrair → mover pra `versions/` → trocar `current` →
prune (mantém os 3 mais novos + o atual + o que está rodando) → oferecer reiniciar.

**Pendência conhecida:** instalações "flat" antigas (binário solto em `~/Nuclear/blender`,
sem `current`) NÃO se auto-atualizam — caem no fallback de abrir a página. Precisam ser
reinstaladas com `instalarNuclear.sh` (layout versionado) ou ter a `_detect_layout`
adaptada. Ver `[[nuclear-auto-update]]` na memória do projeto.

## 8. Troubleshooting

| Sintoma | Causa provável | Ação |
| --- | --- | --- |
| "checksum não confere" | zip trocado, manifesto com hash velho | regerar `version.json` (seção 5, atalho) |
| Nenhum aviso aparece | build instalado == build do manifesto, ou sem `nuclear_version.json` | conferir `NUCLEAR_BUILD`; testar com `NUCLEAR_UPDATE_BUILD=0` |
| "Invalid operator call" | (corrigido) operador modal chamado sem evento | já resolvido: dialogs via `invoke_props_dialog` |
| Clica e abre a página em vez de instalar | instalação flat (sem `current`) | reinstalar no layout versionado |
| Aviso some sozinho | (corrigido) era `popup_menu` | já resolvido: `invoke_props_dialog` |

## 9. Variáveis de ambiente do cliente (debug, sem rebuild)

| Var | Efeito |
| --- | --- |
| `NUCLEAR_UPDATE_URL` | troca a URL do manifesto |
| `NUCLEAR_UPDATE_OFF=1` | desliga a checagem |
| `NUCLEAR_UPDATE_BUILD=0` | finge que o build instalado é 0 (força o aviso) |

## 10. Estado atual

- **Versão publicada:** Nuclear 1.0.0 (Beta) — `NUCLEAR_BUILD = 1`.
- **nuclear.zip:** 728.581.557 bytes, sha256 `64c03233b01f1dc51e0d1cda6c41a5499a1f516ee73b7e3ba6a315aede303c99`.
- **Telas:** diálogos fixos (`invoke_props_dialog`); primeira checagem 3 s após abrir.
