"""Miniatura de cada take — o board visto de uma vez, sem abrir plano por plano.

A lista de takes dizia código, quantos desenhos e quanto dura; o que ela não
dizia era o que estava DESENHADO. Para lembrar o plano, o artista tinha de
entrar nele — e entrar num take é carregar um arquivo. Num board de trinta
planos, rever a sequência custava trinta trocas de arquivo.

A miniatura é renderizada quando o take é salvo (que é por onde a troca de take
passa) e fica em `thumbs/<id do take>.png`, dentro do board: quem abrir o board
em outra máquina vê o mesmo board, e não uma grade de quadros cinzas.

Ela é do PRIMEIRO desenho do take, não do quadro em que o artista parou: é o
quadro que abre o plano, o mesmo que a folha impressa mostraria.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import bpy

from . import gp

THUMB_DIR = "thumbs"

#: Largura da miniatura em pixels. O ícone da interface tem cerca de 100px de
#: largura; o dobro disso cobre tela em HiDPI sem o arquivo virar peso.
THUMB_WIDTH = 320

#: Coleção de previews do Blender (é ela que transforma PNG em ícone de UI).
_PREVIEWS = None

#: Quando cada miniatura foi gerada, para recarregar o ícone quando ela muda.
_LOADED = {}


# ---------------------------------------------------------------------------
# Disco
# ---------------------------------------------------------------------------

def thumb_dir(store) -> Path:
    return Path(store.paths.root) / THUMB_DIR


def thumb_path(store, take) -> Path:
    """Pelo ID e não pelo código: renomear o take não pode perder a miniatura."""
    return thumb_dir(store) / f"{take.id}.png"


def missing(store, takes) -> list:
    """Takes do recorte que ainda não têm miniatura no disco."""
    return [tk for tk in takes if not thumb_path(store, tk).is_file()]


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------

def render_thumb(scene, store, take, ob=None) -> Optional[Path]:
    """Renderiza a miniatura do take a partir da cena ABERTA. Devolve o caminho.

    Renderiza a cena inteira, e não só o objeto do take: o prop trazido da
    biblioteca é um plano com a arte, e escondê-lo daria uma miniatura que não
    corresponde ao plano.

    Nada aqui pode derrubar o salvar do take, então uma falha de render volta
    como `None` — o board mostra o quadro vazio e a vida segue.
    """
    if ob is None:
        ob = gp.find_take_object(take)
    if ob is None or not gp.has_art(ob):
        # Take ainda sem traço nenhum não vira miniatura: seria um retângulo
        # branco igual ao de todos os outros, e o board tem mais a dizer
        # mostrando o quadro vazio — que é a informação "este ainda não existe".
        return None

    destino = thumb_path(store, take)
    destino.parent.mkdir(parents=True, exist_ok=True)

    frames = gp.drawing_frames(ob)
    render = scene.render
    images = render.image_settings
    guardado = {
        "filepath": render.filepath,
        "percentage": render.resolution_percentage,
        "format": images.file_format,
        "color_mode": images.color_mode,
        "transparent": render.film_transparent,
        "media": getattr(images, "media_type", None),
        "frame": scene.frame_current,
    }
    try:
        if frames:
            scene.frame_set(frames[0])
        largura = max(1, render.resolution_x)
        render.resolution_percentage = max(1, min(100, round(100 * THUMB_WIDTH / largura)))
        # Um `.nuc` configurado para sair em vídeo recusa "PNG" no formato — o
        # mesmo tropeço que o worker de export já levou uma vez.
        if hasattr(images, "media_type"):
            images.media_type = "IMAGE"
        images.file_format = "PNG"
        images.color_mode = "RGB"
        render.film_transparent = False
        render.filepath = str(destino.with_suffix(""))
        bpy.ops.render.render(write_still=True)
    except (RuntimeError, ValueError, TypeError) as exc:
        print(f"[storyboard] miniatura de {take.code}: {exc}")
        return None
    finally:
        render.filepath = guardado["filepath"]
        render.resolution_percentage = guardado["percentage"]
        images.file_format = guardado["format"]
        images.color_mode = guardado["color_mode"]
        render.film_transparent = guardado["transparent"]
        if guardado["media"] is not None and hasattr(images, "media_type"):
            images.media_type = guardado["media"]
        scene.frame_set(guardado["frame"])

    return destino if destino.is_file() else None


# ---------------------------------------------------------------------------
# Ícones da interface
# ---------------------------------------------------------------------------

def previews():
    global _PREVIEWS
    if _PREVIEWS is None:
        import bpy.utils.previews
        _PREVIEWS = bpy.utils.previews.new()
    return _PREVIEWS


def icon_id(store, take) -> int:
    """Ícone da miniatura para a interface, ou 0 quando ainda não há uma.

    O ícone é recarregado quando o PNG muda de data no disco — o Blender guarda
    o pixel, então sem isto o board continuaria mostrando o desenho de ontem
    depois de o take ser redesenhado. Só o item daquele take é descartado: uma
    limpeza geral aqui faria os outros se recarregarem em cadeia, a cada redraw.
    """
    caminho = thumb_path(store, take)
    try:
        carimbo = caminho.stat().st_mtime_ns
    except OSError:
        return 0

    pcoll = previews()
    if _LOADED.get(take.id) != carimbo and take.id in pcoll:
        del pcoll[take.id]
    _LOADED[take.id] = carimbo

    if take.id not in pcoll:
        try:
            pcoll.load(take.id, str(caminho), "IMAGE")
        except KeyError:
            return 0
    return pcoll[take.id].icon_id


def forget() -> None:
    """Esquece os ícones já carregados (a próxima tela recarrega do disco)."""
    if _PREVIEWS is not None:
        _PREVIEWS.clear()
    _LOADED.clear()


# ---------------------------------------------------------------------------
# Prévia de uma imagem qualquer
#
# Coleção à parte da do board: lá a chave é o id do take, e uma limpeza de uma
# esvaziaria a outra. Esta serve à imagem que o artista anexa a um prop — ver o
# que se está mandando antes de abrir uma pendência no estúdio.
# ---------------------------------------------------------------------------

#: Extensões que o Blender carrega como preview. Arquivo fora da lista nem é
#: tentado: o `load` não reclama na hora, e o quadrado sairia vazio na tela.
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
                  ".tga", ".exr", ".psd"}

_IMAGES = None
_IMAGES_LOADED = {}


def image_previews():
    global _IMAGES
    if _IMAGES is None:
        import bpy.utils.previews
        _IMAGES = bpy.utils.previews.new()
    return _IMAGES


def load_image_preview(path):
    """Prévia carregada deste arquivo de imagem, ou None.

    Recarrega quando o arquivo muda de data, pelo mesmo motivo da miniatura do
    take: o Blender guarda o pixel, e trocar a imagem escolhida mostraria a
    anterior.

    Separada de `image_icon` porque `icon_id` é 0 em background — ícone é coisa
    de interface — e sem esta função não haveria como um teste headless dizer
    se a prévia foi lida ou se o arquivo foi recusado.
    """
    caminho = Path(path)
    if caminho.suffix.lower() not in IMAGE_SUFFIXES:
        return None
    try:
        carimbo = caminho.stat().st_mtime_ns
    except OSError:
        return None

    chave = str(caminho)
    pcoll = image_previews()
    mudou = _IMAGES_LOADED.get(chave) not in (None, carimbo)
    if mudou and chave in pcoll:
        del pcoll[chave]
    _IMAGES_LOADED[chave] = carimbo

    if chave not in pcoll:
        try:
            # `force_reload` porque tirar da coleção NÃO basta: o Blender guarda
            # o pixel num cache global chaveado pelo caminho, e recarregar o
            # mesmo arquivo devolvia a imagem anterior — o artista trocaria a
            # referência e continuaria vendo a que descartou.
            pcoll.load(chave, chave, "IMAGE", force_reload=mudou)
        except KeyError:
            return None

    prévia = pcoll[chave]
    # `load` não lê o arquivo na hora — ele só é aberto quando alguém pede o
    # tamanho ou o pixel. Um arquivo que só TEM cara de imagem (o print salvo
    # com a extensão errada, o `.png` que na verdade é texto) passa pelo load e
    # viraria um quadrado vazio na tela, com jeito de "ainda carregando".
    if tuple(prévia.image_size) == (0, 0):
        del pcoll[chave]
        _IMAGES_LOADED.pop(chave, None)
        return None
    return prévia


def image_icon(path) -> int:
    """Ícone de um arquivo de imagem do disco, ou 0 quando não dá para mostrar."""
    prévia = load_image_preview(path)
    return prévia.icon_id if prévia is not None else 0


def register():
    previews()


def unregister():
    global _PREVIEWS, _IMAGES
    import bpy.utils.previews

    if _PREVIEWS is not None:
        bpy.utils.previews.remove(_PREVIEWS)
        _PREVIEWS = None
    if _IMAGES is not None:
        bpy.utils.previews.remove(_IMAGES)
        _IMAGES = None
    _LOADED.clear()
    _IMAGES_LOADED.clear()
