"""Ponte com o sistema de aprovacao de assets (aprovacao.rapaduraatomica.com.br).

Serve a duas coisas do board:

* **lista de projetos** — a sigla que abre o nome dos arquivos entregues sai do
  projeto de verdade, nao de um texto digitado a cada board;
* **pendencia de prop** — quando o animador desenha um prop provisorio e anexa
  uma referencia, abre-se la um asset em rascunho com essa imagem, para o prop
  definitivo ser criado por quem faz arte.

O contrato e o da API que ja esta no ar (Fastify): `POST /auth/intranet-login`
devolve um JWT que vai no `Authorization: Bearer`; `POST /assets` e multipart e
exige ARTIST; quem entra com papel de producao usa `POST /producer/assets`.

Modulo puro: so `urllib` da stdlib, sem `bpy` e sem `requests` — o Python do
Nuclear nao tem dependencia externa nenhuma, e assim o cliente e testavel no
host contra um servidor de mentira.
"""

from __future__ import annotations

import json
import mimetypes
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_BASE_URL = "https://aprovacao.rapaduraatomica.com.br/api"

#: Tipo do asset criado para um prop. A API so conhece quatro tipos e nenhum e
#: "prop"; o objeto de cena e arte de cena.
PROP_ASSET_TYPE = "SCENE_ART"

#: Tipo do asset de um animatic entregue daqui. E o que o aprovacao chama de
#: STORYBOARD — o board inteiro, uma cena ou um plano, todos entram como isso.
ANIMATIC_ASSET_TYPE = "STORYBOARD"

#: O que a API aceita em video (conferido no contrato do backend): MP4 ate
#: 500 MB. Conferimos ANTES de subir — descobrir o limite depois de empurrar
#: 600 MB pela rede e o pior jeito de descobrir.
VIDEO_MIME = "video/mp4"
VIDEO_SUFFIX = ".mp4"
MAX_VIDEO_BYTES = 500 * 1024 * 1024

#: Prazo (em dias) que a pendencia leva. E obrigatorio no contrato; o valor
#: existe para o timer de aprovacao do outro lado e nao muda nada no board.
DEFAULT_DEADLINE_DAYS = 7

#: Papeis que NAO podem usar `POST /assets` (a rota e exclusiva do artista).
PRODUCTION_ROLES = ("PRODUCER", "STUDIO_MANAGER")

TIMEOUT = 20.0


class ApprovalError(Exception):
    """Falha de comunicacao ou recusa do servidor, ja em portugues."""


@dataclass
class Session:
    """Credencial viva. Nao guarda senha — so o token que a API devolveu."""

    base_url: str = DEFAULT_BASE_URL
    token: str = ""
    user_id: str = ""
    user_name: str = ""
    role: str = ""

    @property
    def is_production(self) -> bool:
        return self.role in PRODUCTION_ROLES


@dataclass
class Pending:
    """Uma pendencia aberta la, do jeito que a biblioteca do board precisa ver."""

    asset_id: str
    name: str
    status: str
    project: str = ""
    version: Optional[int] = None
    download_url: str = ""
    feedback: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    @property
    def is_done(self) -> bool:
        """Aprovado pelo cliente — a arte definitiva existe e passou."""
        return self.status == "APPROVED"


# ---------------------------------------------------------------------------
# HTTP cru
# ---------------------------------------------------------------------------

def _url(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _open(request: urllib.request.Request, timeout: float, context=None):
    """Executa e traduz as falhas para uma mensagem que cabe numa barra de status."""
    try:
        return urllib.request.urlopen(request, timeout=timeout, context=context)
    except urllib.error.HTTPError as exc:
        with exc:  # sem fechar, o socket da resposta de erro fica pendurado
            corpo = exc.read().decode("utf-8", "replace")
        mensagem = corpo
        try:
            dados = json.loads(corpo)
            mensagem = dados.get("error") or dados.get("message") or corpo
        except (ValueError, AttributeError):
            pass
        if exc.code == 401:
            raise ApprovalError("sessão expirada ou credencial inválida — entre de novo")
        if exc.code == 403:
            raise ApprovalError(f"sem permissão para isto no aprovação: {mensagem}")
        if exc.code == 413:
            raise ApprovalError("a imagem de referência é grande demais (limite de 25 MB)")
        if exc.code == 415:
            raise ApprovalError(f"tipo de arquivo não aceito pelo aprovação: {mensagem}")
        raise ApprovalError(f"o aprovação recusou ({exc.code}): {mensagem[:200]}")
    except (urllib.error.URLError, socket.timeout, ssl.SSLError) as exc:
        motivo = getattr(exc, "reason", exc)
        raise ApprovalError(f"não deu para falar com o aprovação: {motivo}")


def _request(session_or_base, path: str, *, method: str = "GET",
             payload: Optional[dict] = None, body: Optional[bytes] = None,
             content_type: str = "", token: str = "",
             timeout: float = TIMEOUT) -> Any:
    base = (session_or_base.base_url if isinstance(session_or_base, Session)
            else str(session_or_base))
    if isinstance(session_or_base, Session) and not token:
        token = session_or_base.token

    data = body
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(_url(base, path), data=data,
                                     headers=headers, method=method)
    with _open(request, timeout) as resposta:
        cru = resposta.read().decode("utf-8", "replace")
    if not cru:
        return {}
    try:
        return json.loads(cru)
    except ValueError:
        raise ApprovalError("o aprovação respondeu algo que não é JSON "
                            "(o endereço está certo?)")


def _multipart(fields: Dict[str, str], file_field: str, file_path: Path):
    """Monta um corpo multipart/form-data na mao.

    Os campos de TEXTO vao antes do arquivo: a API le o multipart em fluxo e so
    enxerga os campos que chegaram ate o arquivo aparecer.
    """
    boundary = f"----nsb{uuid.uuid4().hex}"
    linhas = bytearray()

    def escreve(texto: str) -> None:
        linhas.extend(texto.encode("utf-8"))

    for chave, valor in fields.items():
        if valor is None or valor == "":
            continue
        escreve(f"--{boundary}\r\n")
        escreve(f'Content-Disposition: form-data; name="{chave}"\r\n\r\n')
        escreve(f"{valor}\r\n")

    tipo = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
    escreve(f"--{boundary}\r\n")
    escreve(f'Content-Disposition: form-data; name="{file_field}"; '
            f'filename="{file_path.name}"\r\n')
    escreve(f"Content-Type: {tipo}\r\n\r\n")
    linhas.extend(file_path.read_bytes())
    escreve(f"\r\n--{boundary}--\r\n")
    return bytes(linhas), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# Sessao
# ---------------------------------------------------------------------------

def login(username: str, password: str, base_url: str = DEFAULT_BASE_URL,
          timeout: float = TIMEOUT) -> Session:
    """Entra com o MESMO usuario e senha da intranet (Painel).

    Quem tem e-mail cadastrado pode digitar o e-mail: a rota local aceita
    e-mail, a da intranet aceita o usuario. Tentamos a que casa com o que foi
    digitado e caimos na outra se ela recusar — foi o que o app do celular
    precisou fazer.
    """
    usuario = (username or "").strip()
    senha = password or ""
    if not usuario or not senha:
        raise ApprovalError("informe usuário e senha")

    rotas = (["/auth/login", "/auth/intranet-login"] if "@" in usuario
             else ["/auth/intranet-login", "/auth/login"])
    campos = {"/auth/login": {"email": usuario, "password": senha},
              "/auth/intranet-login": {"username": usuario, "password": senha}}

    primeira: Optional[ApprovalError] = None
    for rota in rotas:
        try:
            dados = _request(base_url, rota, method="POST",
                             payload=campos[rota], timeout=timeout)
        except ApprovalError as exc:
            # Guarda a falha da rota que CASA com o que foi digitado: a outra
            # recusa por formato ("informe um e-mail") e essa mensagem só
            # confundiria quem errou a senha.
            if primeira is None:
                primeira = exc
            continue
        user = dados.get("user") or {}
        return Session(base_url=base_url, token=dados.get("token", ""),
                       user_id=user.get("id", ""), user_name=user.get("name", ""),
                       role=user.get("role", ""))
    raise primeira or ApprovalError("não foi possível entrar")


# ---------------------------------------------------------------------------
# Consultas
# ---------------------------------------------------------------------------

def list_projects(session: Session) -> List[dict]:
    """Projetos ativos, na ordem em que a API devolve (alfabetica)."""
    return _request(session, "/projects").get("projects", [])


def list_clients(session: Session, project_id: str) -> List[dict]:
    query = urllib.parse.urlencode({"projectId": project_id})
    return _request(session, f"/clients?{query}").get("clients", [])


def list_folders(session: Session, project_id: str) -> List[dict]:
    return _request(session, f"/projects/{project_id}/folders").get("folders", [])


def my_assets(session: Session) -> List[dict]:
    """Assets criados por quem esta logado — a fonte da volta das pendencias."""
    return _request(session, "/assets/mine").get("assets", [])


def project_assets(session: Session, project_id: str) -> List[dict]:
    """Assets do projeto que o usuario pode ver — vale para qualquer papel."""
    return _request(session, f"/projects/{project_id}/assets").get("assets", [])


def pending_state(session: Session, asset_ids,
                  project_id: str = "") -> Dict[str, Pending]:
    """Estado atual das pendencias pedidas, indexado pelo id do asset.

    Uma consulta so para todas: sao poucas por board e as rotas devolvem lista.
    Consultamos pelo PROJETO quando o board esta ligado a um, porque
    `/assets/mine` e exclusiva do artista — quem entra com papel de producao
    tomaria 403 e o board diria que a pendencia sumiu.
    """
    procurados = {i for i in asset_ids if i}
    if not procurados:
        return {}

    if project_id:
        try:
            lista = project_assets(session, project_id)
        except ApprovalError:
            lista = my_assets(session) if not session.is_production else []
    else:
        lista = my_assets(session)

    achados: Dict[str, Pending] = {}
    for asset in lista:
        if asset.get("id") in procurados:
            achados[asset["id"]] = Pending(
                asset_id=asset["id"],
                name=asset.get("name", ""),
                status=asset.get("status", ""),
                project=asset.get("project", ""),
                version=asset.get("version"),
                download_url=asset.get("downloadUrl") or "",
                feedback=asset.get("producerFeedback") or "",
                extra=asset,
            )
    return achados


# ---------------------------------------------------------------------------
# Criacao da pendencia
# ---------------------------------------------------------------------------

def create_request(session: Session, *, name: str, project_id: str,
                   client_id: str, reference: Path, description: str = "",
                   folder_id: str = "", deadline_days: int = DEFAULT_DEADLINE_DAYS,
                   asset_type: str = PROP_ASSET_TYPE,
                   timeout: float = 60.0) -> Pending:
    """Abre a pendencia: um asset com a imagem de referencia como versao 1.

    Ele nasce em RASCUNHO de proposito — a referencia nao e a arte final, e sim
    o pedido. Quem for criar o prop sobe a arte de verdade como versao nova e a
    manda seguir o fluxo normal de aprovacao.
    """
    reference = Path(reference)
    if not reference.is_file():
        raise ApprovalError(f"imagem de referência não encontrada: {reference}")
    if not project_id:
        raise ApprovalError("este board ainda não está ligado a um projeto do aprovação")
    if not client_id:
        raise ApprovalError("o projeto escolhido não tem nenhum contato de cliente "
                            "cadastrado — o aprovação exige um para abrir a pendência")

    campos = {
        "name": name,
        "description": description,
        "type": asset_type,
        "projectId": project_id,
        "clientId": client_id,
        "folderId": folder_id,
        "deadlineDays": str(int(deadline_days)),
    }
    # Quem entra com papel de producao nao passa pela rota do artista; a rota
    # dele exige dizer se o cliente ja recebe (aqui, nunca: e um pedido interno).
    rota = "/assets"
    if session.is_production:
        rota = "/producer/assets"
        campos["sendToClient"] = "false"

    body, content_type = _multipart(campos, "file", reference)
    dados = _request(session, rota, method="POST", body=body,
                     content_type=content_type, timeout=timeout)
    asset = dados.get("asset") or {}
    if not asset.get("id"):
        raise ApprovalError("o aprovação não devolveu a pendência criada")
    return Pending(asset_id=asset["id"], name=asset.get("name", name),
                   status=asset.get("status", "DRAFT"), extra=asset)


def check_video(video: Path) -> Path:
    """Recusa aqui o que o servidor recusaria depois de subir o arquivo inteiro."""
    video = Path(video)
    if not video.is_file():
        raise ApprovalError(f"vídeo não encontrado: {video}")
    if video.suffix.lower() != VIDEO_SUFFIX:
        raise ApprovalError(
            f"o aprovação só recebe {VIDEO_SUFFIX} em vídeo; este é {video.suffix} "
            "(entregue em MP4 e guarde o outro formato para a edição)")
    tamanho = video.stat().st_size
    if tamanho > MAX_VIDEO_BYTES:
        mb, teto = tamanho / (1024 * 1024), MAX_VIDEO_BYTES / (1024 * 1024)
        raise ApprovalError(f"o vídeo tem {mb:.0f} MB e o limite é {teto:.0f} MB "
                            "— entregue por cena em vez do projeto inteiro")
    return video


def deliver_video(session: Session, *, name: str, project_id: str, client_id: str,
                  video: Path, description: str = "", folder_id: str = "",
                  deadline_days: int = DEFAULT_DEADLINE_DAYS,
                  timeout: float = 600.0) -> Pending:
    """Entrega o animatic no aprovação como um asset de STORYBOARD.

    Mesma porta da pendência de prop (o contrato do backend é um só), com dois
    ajustes: o tipo é o do storyboard e o tempo limite é largo, porque aqui sobe
    um vídeo e não uma imagem de referência.
    """
    video = check_video(video)
    return create_request(session, name=name, project_id=project_id,
                          client_id=client_id, reference=video,
                          description=description, folder_id=folder_id,
                          deadline_days=deadline_days,
                          asset_type=ANIMATIC_ASSET_TYPE, timeout=timeout)


def download_file(url: str, destination: Path, timeout: float = 120.0) -> Path:
    """Baixa a arte aprovada para dentro do board.

    A URL vem assinada pelo proprio aprovacao (MinIO ou Dropbox) e ja carrega a
    credencial dela: nao mandamos o token junto.
    """
    if not url:
        raise ApprovalError("esta pendência não tem arquivo para baixar")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"Accept": "*/*"})
    with _open(request, timeout) as resposta:
        conteudo = resposta.read()
    destination.write_bytes(conteudo)
    return destination
