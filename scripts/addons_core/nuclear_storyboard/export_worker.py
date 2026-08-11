"""Worker de export: roda num Nuclear headless, fora da sessão do artista.

    nuclear --background --python export_worker.py -- --project <dir> [opções]

Por que um processo separado: renderizar os desenhos exige abrir o `.nuc` de
cada take, e fazer isso na sessão aberta jogaria fora o que o artista está
desenhando. Aqui o arquivo do artista nunca é tocado.

Ele imprime uma linha `PROGRESS <feito> <total> <rótulo>` por etapa, que o
operador modal na GUI lê para mostrar andamento, e termina com `DONE` ou
`FAILED <mensagem>`.

O render usa o pipeline normal (EEVEE): `render.opengl` não existe em background
— "no opengl context".
"""

from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path

import bpy


def log(*parts) -> None:
    print(*parts)
    sys.stdout.flush()


def progress(done: int, total: int, label: str) -> None:
    log(f"PROGRESS {done} {total} {label}")


def render_take(store, take, force: bool = False) -> int:
    """Renderiza cada desenho do take para PNG e grava o caminho no índice."""
    from nuclear_storyboard import gp

    path = store.paths.abs(take.file)
    if not path.is_file():
        # Take criado mas nunca aberto no canvas: não há o que renderizar. Quem
        # reclama disso é a RN01 ("menos de 2 desenhos"), com a mensagem certa.
        log(f"take {take.code}: sem canvas ainda, nada a renderizar")
        return 0

    bpy.ops.wm.open_mainfile(filepath=str(path))
    scene = bpy.context.scene
    # `adopt`: take que veio do disco sem índice tem id novo, e o desenho no
    # arquivo carrega o antigo — sem casar os dois, o render pula o take inteiro.
    ob = gp.find_take_object(take, adopt=True)
    if ob is None:
        raise RuntimeError(f"take {take.code}: o arquivo não tem canvas")

    gp.sync_drawings_from_gp(take, ob)
    gp.setup_scene(scene, store.project)
    for layer in ob.data.layers:
        gp.flatten_layer(layer)

    # Um `.nuc` que veio de outro fluxo pode estar configurado para sair em
    # VÍDEO — e aí `file_format` só aceita FFMPEG e pôr "PNG" levanta
    # `enum "PNG" not found in ('FFMPEG')`. Achado abrindo um animatic real do
    # DPE, feito para renderizar MP4 direto.
    settings = scene.render.image_settings
    if hasattr(settings, "media_type"):
        settings.media_type = "IMAGE"
    settings.file_format = "PNG"
    settings.color_mode = "RGB"
    scene.render.film_transparent = False

    slug = take.code or take.id
    rendered = 0
    for index, drawing in enumerate(take.drawings, start=1):
        destination = store.paths.drawings / f"{slug}_D{index:03d}.png"
        if destination.is_file() and not force and drawing.png:
            continue
        scene.frame_set(drawing.frame)
        scene.render.filepath = str(destination.with_suffix(""))
        bpy.ops.render.render(write_still=True)
        if not destination.is_file():
            raise RuntimeError(f"take {take.code}: render não gerou {destination.name}")
        drawing.png = store.paths.rel(destination)
        rendered += 1
    return rendered


def render_thumb_take(store, take, force: bool = False) -> int:
    """Miniatura do take para o board, abrindo o `.nuc` dele.

    Só faz sentido aqui, num processo à parte: gerar a miniatura na sessão do
    artista exigiria abrir o arquivo de cada take, jogando fora o que ele está
    desenhando. O caminho normal é outro — a miniatura sai sozinha quando o take
    é salvo; isto atende ao board feito antes das miniaturas existirem.
    """
    from nuclear_storyboard import gp, thumbs

    if thumbs.thumb_path(store, take).is_file() and not force:
        return 0
    path = store.paths.abs(take.file)
    if not path.is_file():
        log(f"take {take.code}: sem canvas ainda, nada a desenhar")
        return 0

    bpy.ops.wm.open_mainfile(filepath=str(path))
    ob = gp.find_take_object(take, adopt=True)
    if ob is None:
        log(f"take {take.code}: o arquivo não tem canvas")
        return 0
    # Take adotado do disco: o índice nasceu sem desenho nenhum e o arquivo tem
    # todos — sem alinhar aqui, ele iria para o animatic como plano vazio e a
    # validação recusaria o export ("menos de 2 desenhos") com a arte pronta ao
    # lado. Só quando o índice está vazio: take que já tem desenho pode ter um
    # "novo desenho" ainda não gravado no `.nuc`, e reescrever por aqui apagaria
    # justamente o que o artista acabou de criar.
    if not take.drawings:
        gp.sync_drawings_from_gp(take, ob)

    gp.setup_scene(bpy.context.scene, store.project)
    for layer in ob.data.layers:
        gp.flatten_layer(layer)
    return 1 if thumbs.render_thumb(bpy.context.scene, store, take, ob) else 0


def main(argv) -> int:
    parser = argparse.ArgumentParser(prog="export_worker")
    parser.add_argument("--project", required=True)
    parser.add_argument("--takes", default="", help="ids separados por vírgula; vazio = todos")
    parser.add_argument("--force", action="store_true", help="re-renderiza PNGs existentes")
    parser.add_argument("--thumbs", action="store_true",
                       help="só as miniaturas do board, sem render de desenho")
    parser.add_argument("--video", default="", help="caminho do MP4 a gerar")
    parser.add_argument("--kdenlive", default="", help="caminho do .kdenlive a gerar")
    parser.add_argument("--per-take-dir", default="",
                        help="pasta onde sai UM vídeo por take, com nome canônico")
    parser.add_argument("--format", default="MP4",
                        help="MP4 (revisão) ou DNXHR (edição); a extensão sai daqui")
    args = parser.parse_args(argv)

    from nuclear_storyboard.core import ProjectStore, build_timeline
    from nuclear_storyboard.core.exporter import output_format, run_export
    from nuclear_storyboard.core.kdenlive import write_kdenlive
    from nuclear_storyboard.core.naming import take_basename_by_id
    from nuclear_storyboard.core.rules import blocks_export, validate_project

    store = ProjectStore.load(Path(args.project))
    formato = output_format(args.format)
    wanted = {t for t in args.takes.split(",") if t}
    takes = [tk for _, _, tk in store.project.iter_takes()
             if not wanted or tk.id in wanted]
    if not takes:
        log("FAILED nenhum take para exportar")
        return 1

    if args.thumbs:
        feitas = alinhados = 0
        for i, take in enumerate(takes):
            progress(i, len(takes), f"miniatura de {take.code}")
            antes = len(take.drawings)
            feitas += render_thumb_take(store, take, args.force)
            alinhados += 1 if len(take.drawings) != antes else 0
        # Grava só se alguma coisa mudou: o `save` também reescreve a biblioteca,
        # que num episódio é dividida entre as cenas.
        if alinhados:
            store.save()
        progress(len(takes), len(takes), "concluído")
        log(f"{feitas} miniatura(s)")
        if alinhados:
            log(f"{alinhados} take(s) com os desenhos alinhados ao arquivo")
        log("DONE")
        return 0

    # O recorte vale para a validação e para a montagem: exportar uma cena é
    # exportar um animatic dela, começando no frame 0 (RF-13).
    scope = {tk.id for tk in takes} if wanted else None

    montar = bool(args.video or args.kdenlive or args.per_take_dir)
    if montar:
        # Validar ANTES de renderizar: não faz sentido gastar minutos de render
        # para descobrir no fim que um take não tinha os 2 desenhos.
        issues = validate_project(store.project, store.library, store.paths, scope)
        blocking = [i for i in blocks_export(issues, store.project.settings.strict_hex_link)
                    if i.code != "RF-A01"]  # PNG/áudio ausente ainda vai ser gerado
        if blocking:
            for issue in blocking[:10]:
                log(f"  {issue}")
            log(f"FAILED {len(blocking)} problema(s) impedem o export")
            return 1

    total = (len(takes) + (1 if args.video else 0) + (1 if args.kdenlive else 0)
             + (len(takes) if args.per_take_dir else 0))
    done = 0
    for take in takes:
        progress(done, total, f"renderizando {take.code}")
        count = render_take(store, take, args.force)
        store.save()
        done += 1
        log(f"take {take.code}: {count} desenho(s) renderizados")

    if montar:
        slices, _ = build_timeline(store.project, scope)
        if args.kdenlive:
            progress(done, total, "escrevendo .kdenlive")
            out = write_kdenlive(store.project, store.paths, Path(args.kdenlive), slices)
            done += 1
            log(f"kdenlive: {out}")
        if args.video:
            progress(done, total, "montando o vídeo")
            out = run_export(store.project, store.paths, Path(args.video), slices,
                             formato)
            done += 1
            log(f"video: {out}")
        if args.per_take_dir:
            # Cada take vira um animatic próprio, começando no frame 0 — é o
            # arquivo que a animação recebe. O nome segue o padrão do estúdio
            # (PROJETO_EP00_C00T00) para casar com o resto da produção.
            destino = Path(args.per_take_dir)
            destino.mkdir(parents=True, exist_ok=True)
            usados = set()
            for take in takes:
                progress(done, total, f"vídeo do take {take.code}")
                nome = take_basename_by_id(store.project, take.id) or (take.code or take.id)
                # Dois takes com o mesmo código na mesma cena (o board avisa,
                # mas não impede) cairiam no MESMO arquivo e o segundo apagaria
                # o primeiro sem dizer nada.
                if nome in usados:
                    base, i = nome, 2
                    while nome in usados:
                        nome = f"{base}_{i}"
                        i += 1
                    log(f"AVISO: {take.code} tem o mesmo nome de outro take; "
                        f"saiu como {nome}")
                usados.add(nome)
                fatias, _frames = build_timeline(store.project, {take.id})
                out = run_export(store.project, store.paths,
                                 destino / f"{nome}{formato.suffix}", fatias,
                                 formato)
                done += 1
                log(f"take {take.code}: {out}")

    progress(total, total, "concluído")
    log("DONE")
    return 0


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    try:
        sys.exit(main(argv))
    except Exception as exc:  # noqa: o worker precisa reportar qualquer falha
        traceback.print_exc()
        log(f"FAILED {exc}")
        sys.exit(1)
