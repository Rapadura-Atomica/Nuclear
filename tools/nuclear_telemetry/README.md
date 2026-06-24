<!-- SPDX-FileCopyrightText: 2026 Blender Authors -->
<!-- SPDX-FileCopyrightText: 2026 Rapadura Atômica -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Nuclear — telemetria de presença

Registro de **presença** das instalações do Nuclear: mostra numa página web quais
máquinas estão online agora e quais estão offline (com o último horário visto).
**Não bloqueia nem limita nada** — é só um espelho de "quem está rodando".

> Nuclear é um fork do Blender. Os arquivos mantêm o copyright original
> "Blender Authors" **somado** ao da Rapadura Atômica, e a licença
> `GPL-2.0-or-later`. **Não remova esses cabeçalhos** — adicione o seu ao lado.
> Ver [Licença e privacidade](#licença-e-privacidade-leia-antes-de-mexer).

## Mapa do código (para o dev)

| Caminho | Papel |
| --- | --- |
| `scripts/startup/nuclear_telemetry.py` | **Cliente** embutido no build. Ping no startup + heartbeat a cada 5 min, em background. Falha em silêncio se o servidor estiver fora. |
| `server/app.py` | **Referência canônica** — servidor Flask + SQLite. Edite aqui primeiro. |
| `server/ping.php` / `server/admin.php`* | Porta PHP do mesmo servidor para hospedagem compartilhada (HostGator). Mantenha em paridade com `app.py`. |
| `server/templates/dashboard.html` | Painel público (bolinha verde/cinza). |
| `server/templates/admin.html` | Painel de admin (apelido + região), protegido por senha. |

> *No deploy (`Nuclear_web/nuclear-api/`) os arquivos PHP são `ping.php`,
> `index.php` (= dashboard) e `admin.php`. **A fonte canônica é este diretório
> `server/`**; o `nuclear-api/` é cópia de deploy. Ao mudar algo, mude aqui e
> propague para o deploy — não edite só o deploy, senão as duas cópias divergem.

### Modelo de dados (tabela `machines`)

| Coluna | Origem | Sobrescrita pelo ping? |
| --- | --- | --- |
| `machine_id` (PK), `hostname`, `username`, `version`, `last_event`, `first_seen`, `last_seen` | cliente | sim (exceto `first_seen`) |
| `region` | GeoIP no 1º ping **ou** admin | **não** — preservada entre pings |
| `alias` | admin | **não** — preservada entre pings |

`alias` e `region` ficam **fora** do `ON CONFLICT … DO UPDATE`: rótulos definidos
no admin são a fonte da verdade e nunca são apagados por um heartbeat.

## 1. Subir o servidor

**Flask (VPS / teste local):**

```sh
cd tools/nuclear_telemetry/server
pip install -r requirements.txt
python app.py            # http://127.0.0.1:8000
gunicorn -b 0.0.0.0:8000 app:app   # produção
```

**PHP (hospedagem compartilhada):** suba `ping.php`, `index.php` e `admin.php`
em `public_html/nuclear/`. Não precisa de Python nem Passenger.

### Variáveis de ambiente (Flask)

| Var | Default | Função |
| --- | --- | --- |
| `NUCLEAR_DB` | `./telemetry.db` | arquivo SQLite |
| `NUCLEAR_TOKEN` | *(definido)* | pings precisam mandar `X-Nuclear-Token` igual |
| `NUCLEAR_ONLINE_SECS` | `600` | segundos sem ping para virar "offline" |
| `NUCLEAR_ADMIN_USER` / `NUCLEAR_ADMIN_TOKEN` | `admin` / *(definido)* | **login do `/admin` — segredo SEPARADO do token de ping** |
| `NUCLEAR_GEOIP` | `1` | `0` desliga o preenchimento automático de região |
| `PORT` | `8000` | porta do servidor de teste |

No PHP, os mesmos valores são constantes no topo de `ping.php`/`admin.php`
(`$TOKEN`, `$ADMIN_USER`, `$ADMIN_PASSWORD`, `$GEOIP_AUTOFILL`). **Troque a senha
de admin antes de subir.**

## 2. Apontar o cliente para o servidor

```sh
export NUCLEAR_TELEMETRY_URL="https://SUA-HOSPEDAGEM.com/nuclear/ping.php"
export NUCLEAR_TELEMETRY_TOKEN="seu-segredo"   # = NUCLEAR_TOKEN do servidor
export NUCLEAR_TELEMETRY_OFF="1"               # desliga a telemetria no cliente
```

Enquanto a URL for o placeholder `CHANGE-ME`, o cliente fica quieto e não envia
nada — o build não "telefona" para lugar nenhum até você configurar.

## 3. Localizar as suas máquinas (apelido + região)

- **Região automática:** no 1º ping de uma máquina nova, o servidor resolve o
  **estado** pelo IP (via `ip-api.com`, timeout curto, falha em silêncio).
  Granularidade de estado é o que é confiável — cidade pequena erra, e máquinas
  no mesmo escritório saem do mesmo IP. Por isso o **valor manual sempre vence**.
- **Apelido e região manuais:** acesse `/admin` (login pelo segredo de admin),
  defina o apelido (ex.: `Estação Anim 01`) e a região (ex.: `CEARÁ`). Os rótulos
  aparecem no painel público e sobrevivem a todos os pings seguintes.
- O admin também permite **remover** uma máquina do painel.

### Teste ponta-a-ponta

```sh
# terminal 1 — servidor
cd tools/nuclear_telemetry/server && python app.py
# terminal 2 — simula um ping
curl -X POST http://127.0.0.1:8000/api/ping \
  -H 'Content-Type: application/json' \
  -d '{"machine_id":"teste123","hostname":"PC-Anim-01","user":"israel","version":"5.0","event":"startup"}'
```

Abra `http://127.0.0.1:8000` (painel) e `http://127.0.0.1:8000/admin` (admin).

## Licença e privacidade (leia antes de mexer)

- **Licença.** Código sob `GPL-2.0-or-later`, herdado do Blender. Telemetria
  **não** fere a GPL, mas mantenha os cabeçalhos SPDX e a oferta de código-fonte
  (já apontada em `version.json → notes_url`). Ao editar, **acrescente** o
  copyright "Rapadura Atômica"; nunca remova o "Blender Authors".
- **O que é coletado.** `machine_id` anônimo por instalação, hostname, usuário do
  SO, versão, tipo de evento e — com `NUCLEAR_GEOIP=1` — o **estado** derivado do
  IP no primeiro ping. O IP em si **não** é armazenado, só a região resultante.
- **LGPD.** IP e localização são dados pessoais. Como o build envia dados para
  fora, **declare a telemetria e a região no acordo de beta** e informe o opt-out
  (`NUCLEAR_TELEMETRY_OFF=1`). Para desativar de vez a coleta de região no
  servidor, use `NUCLEAR_GEOIP=0` (ou `$GEOIP_AUTOFILL = false` no PHP).
