<!-- SPDX-FileCopyrightText: 2026 Blender Authors -->
<!-- SPDX-License-Identifier: GPL-2.0-or-later -->

# Nuclear — telemetria de presença

Mostra, numa página web, **quais máquinas estão rodando o Nuclear agora** (online) e
quais não (offline). É só registro de presença: **não bloqueia nem limita nada**.

## Peças

| Onde | O quê |
| --- | --- |
| `scripts/startup/nuclear_telemetry.py` | Cliente embutido no build. Manda um ping no startup + heartbeat a cada 5 min, tudo em background. Falha em silêncio se o servidor estiver fora. |
| `tools/nuclear_telemetry/server/app.py` | Servidor Flask + SQLite que recebe os pings. |
| `tools/nuclear_telemetry/server/templates/dashboard.html` | A página com bolinha verde/cinza. |

## 1. Subir o servidor (na sua hospedagem)

```sh
cd tools/nuclear_telemetry/server
pip install -r requirements.txt
python app.py            # teste local em http://127.0.0.1:8000
```

Em produção, sirva com gunicorn (VPS) ou mod_wsgi/Passenger (hospedagem compartilhada):

```sh
gunicorn -b 0.0.0.0:8000 app:app
```

Variáveis de ambiente do servidor:

| Var | Default | Função |
| --- | --- | --- |
| `NUCLEAR_DB` | `./telemetry.db` | arquivo SQLite |
| `NUCLEAR_TOKEN` | *(vazio)* | se setado, pings precisam mandar o header `X-Nuclear-Token` igual |
| `NUCLEAR_ONLINE_SECS` | `600` | segundos sem ping pra virar "offline" |
| `PORT` | `8000` | porta do servidor de teste |

## 2. Apontar o cliente para o servidor

Edite o topo de `scripts/startup/nuclear_telemetry.py`:

```python
SERVER_URL   = "https://SUA-HOSPEDAGEM.com/api/ping"
SHARED_TOKEN = ""   # opcional; precisa bater com NUCLEAR_TOKEN no servidor
```

Ou, sem recompilar, via variáveis de ambiente na máquina que roda o Nuclear:

```sh
export NUCLEAR_TELEMETRY_URL="https://SUA-HOSPEDAGEM.com/api/ping"
export NUCLEAR_TELEMETRY_TOKEN="seu-segredo"   # opcional
export NUCLEAR_TELEMETRY_OFF="1"               # desliga a telemetria
```

> Enquanto a URL ainda for o placeholder `CHANGE-ME`, o cliente fica quieto e não
> manda nada — então o build não "telefona" para lugar nenhum até você configurar.

## 3. Testar a ponta-a-ponta local

```sh
# terminal 1 — servidor
cd tools/nuclear_telemetry/server && python app.py

# terminal 2 — simula um ping de cliente
curl -X POST http://127.0.0.1:8000/api/ping \
  -H 'Content-Type: application/json' \
  -d '{"machine_id":"teste123","hostname":"PC-Anim-01","user":"israel","version":"5.0","event":"startup"}'
```

Abra `http://127.0.0.1:8000` — a máquina `PC-Anim-01` aparece online.

## Privacidade

O cliente manda: id anônimo por instalação, hostname, usuário do SO, versão e o tipo
de evento. Por ser um build que envia dados pra fora, coloque uma linha no acordo de
beta avisando que há telemetria de uso.
