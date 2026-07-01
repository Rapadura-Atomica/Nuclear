# SPDX-FileCopyrightText: 2026 Blender Authors
# SPDX-FileCopyrightText: 2026 Rapadura Atômica
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""
Teste controlado, offline, do cliente de relatorio de falha
(`scripts/startup/nuclear_crash_report.py`).

Roda o CODIGO REAL do cliente, sem Blender e sem PHP:
  - mocka o minimo de `bpy` para o modulo carregar;
  - sobe um servidor HTTP local de verdade (stdlib) que finge ser o `crash.php`,
    recebe o POST e grava o corpo recebido;
  - exercita os tres caminhos: deteccao de sessao travada, gatilho de teste
    (NUCLEAR_CRASH_TEST=1) e o envio (round-trip de rede no localhost), checando
    que o relatorio chega com estudio + descricao + backtrace + token.

Uso:
    python3 tools/nuclear_telemetry/selftest_crash.py

Sai com codigo 0 se tudo passou, !=0 caso contrario. Nao toca a rede externa nem o
servidor de producao.

Cobre o cliente. O `crash.php` em si (formatacao do .txt, sanitizacao do nome) é
validado por `php -l` + revisao; para um teste ponta-a-ponta com a UI real e o
crash.php, rode o Blender com NUCLEAR_CRASH_TEST=1 apontando para o endpoint.
"""

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import types
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLIENT = os.path.normpath(os.path.join(HERE, "..", "..", "scripts", "startup", "nuclear_crash_report.py"))


# --- mock minimo do bpy ------------------------------------------------------

def _install_fake_bpy(config_dir, tempdir):
    bpy = types.ModuleType("bpy")
    bpy.app = types.SimpleNamespace(
        version_string="Nuclear 1.4.2 (Beta)",
        background=False,
        tempdir=tempdir,
        timers=types.SimpleNamespace(register=lambda *a, **k: None),
    )
    bpy.utils = types.SimpleNamespace(
        user_resource=lambda kind, create=False: config_dir,
    )

    class _Operator:
        bl_options = set()

    bpy.types = types.SimpleNamespace(Operator=_Operator)
    props = types.ModuleType("bpy.props")
    props.StringProperty = lambda **k: None
    sys.modules["bpy"] = bpy
    sys.modules["bpy.props"] = props


def _load_client():
    spec = importlib.util.spec_from_file_location("nuclear_crash_report", CLIENT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- servidor que finge ser o crash.php --------------------------------------

class _Receiver(BaseHTTPRequestHandler):
    received = []  # (headers, parsed-json-body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        try:
            parsed = json.loads(body.decode("utf-8"))
        except Exception:
            parsed = None
        _Receiver.received.append((dict(self.headers), parsed))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def log_message(self, *args):
        pass  # silencio


# --- runner ------------------------------------------------------------------

def main():
    failures = []

    def check(name, cond, detail=""):
        status = "OK  " if cond else "FALHA"
        print("  [%s] %s%s" % (status, name, (" -> " + detail) if detail and not cond else ""))
        if not cond:
            failures.append(name)

    work = tempfile.mkdtemp(prefix="nuclear_crash_selftest_")
    config_dir = os.path.join(work, "config")
    os.makedirs(config_dir, exist_ok=True)
    sess_tempdir = os.path.join(work, "tmp", "blender_sess")
    os.makedirs(sess_tempdir, exist_ok=True)

    _install_fake_bpy(config_dir, sess_tempdir)
    ncr = _load_client()

    server = HTTPServer(("127.0.0.1", 0), _Receiver)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    os.environ["NUCLEAR_CRASH_URL"] = "http://127.0.0.1:%d/crash.php" % port
    os.environ["NUCLEAR_TELEMETRY_TOKEN"] = "token-de-teste"
    os.environ.pop("NUCLEAR_CRASH_OFF", None)
    os.environ.pop("NUCLEAR_CRASH_TEST", None)

    print("1) Deteccao: sessao travada (sentinela orfa de PID morto)")
    sd = ncr._sessions_dir()
    dead_pid = 999999
    with open(os.path.join(sd, "session_%d.json" % dead_pid), "w") as fh:
        json.dump({"pid": dead_pid, "start_time": "2026-06-30T21:00:00+00:00",
                   "version": "Nuclear 1.4.2 (Beta)", "hostname": "PC-Anim-01",
                   "username": "israel", "machine_id": "abc123def456789"}, fh)
    ncr._pending_crash = None
    ncr._detect_previous_crash()
    check("detectou crash", ncr._pending_crash is not None)
    check("limpou a sentinela travada",
          not os.path.exists(os.path.join(sd, "session_%d.json" % dead_pid)))

    print("2) Falso positivo: instancia ainda viva (PID atual) nao e crash")
    ncr._pending_crash = None
    live = os.path.join(sd, "session_%d.json" % os.getpid())
    with open(live, "w") as fh:
        json.dump({"pid": os.getpid(), "start_time": "x"}, fh)
    ncr._detect_previous_crash()
    check("ignorou instancia viva", ncr._pending_crash is None)
    check("sentinela viva preservada", os.path.exists(live))
    os.remove(live)

    print("3) Dead-man switch: grava e remove a propria sentinela")
    ncr._write_own_sentinel()
    own = ncr._own_sentinel_path()
    check("gravou sentinela da sessao", os.path.exists(own))
    ncr._on_clean_exit()
    check("saida limpa removeu a sentinela", not os.path.exists(own))

    print("4) Gatilho de teste: NUCLEAR_CRASH_TEST=1 forca crash sintetico")
    os.environ["NUCLEAR_CRASH_TEST"] = "1"
    ncr._pending_crash = None
    ncr._detect_previous_crash()
    check("crash sintetico criado", ncr._pending_crash is not None)
    os.environ.pop("NUCLEAR_CRASH_TEST", None)

    print("5) Envio: round-trip de rede ate o 'crash.php' local")
    _Receiver.received = []
    ncr._pending_crash = {
        "crashed_at": "2026-06-30T21:00:00+00:00",
        "crashed_version": "Nuclear 1.4.2 (Beta)",
        "blender_log": "Backtrace de teste: 0x00 funcao_que_explodiu()",
    }
    ncr._send_report("Estudio Rapadura", "travou ao salvar o arquivo")
    deadline = time.time() + 5
    while not _Receiver.received and time.time() < deadline:
        time.sleep(0.05)
    check("servidor recebeu 1 POST", len(_Receiver.received) == 1,
          "recebidos=%d" % len(_Receiver.received))
    if _Receiver.received:
        headers, body = _Receiver.received[0]
        token = {k.lower(): v for k, v in headers.items()}.get("x-nuclear-token")
        check("token enviado no header", token == "token-de-teste", repr(token))
        check("estudio no payload", (body or {}).get("studio") == "Estudio Rapadura")
        check("descricao no payload", (body or {}).get("description") == "travou ao salvar o arquivo")
        check("backtrace no payload", "explodiu" in (body or {}).get("blender_log", ""))
        check("machine_id presente", bool((body or {}).get("machine_id")))

    server.shutdown()

    print()
    if failures:
        print("RESULTADO: %d verificacao(oes) falharam: %s" % (len(failures), ", ".join(failures)))
        return 1
    print("RESULTADO: todos os testes passaram.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
