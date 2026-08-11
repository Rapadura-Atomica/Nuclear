"""Operadores do canvas: abrir o take, desenhos, camadas e a trava do BG."""

from __future__ import annotations

import bpy
from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from . import gp, state, sync, takefile
from .translations import _, apply_context


class NSB_OT_open_take(Operator):
    bl_idname = "nsb.open_take"
    bl_label = "Open take in canvas"
    bl_description = "Opens (or creates) the take .nuc and sets the drawing scene up"

    @classmethod
    def poll(cls, context):
        return sync.current_take(context) is not None

    def execute(self, context):
        from . import audioedit

        store = state.require_store()
        take = sync.current_take(context)
        episode = sync.current_episode(context)
        scene_obj = sync.current_scene(context)

        # O aviso "recarregado do editor" é do take que estava aberto; deixá-lo
        # na tela no take seguinte é dizer que algo aconteceu aqui.
        audioedit.LAST_MESSAGE = ""

        current = takefile.current_take_of_file(store)
        if current is not None and current.id != take.id:
            # Sai do take atual com os desenhos já reconciliados.
            takefile.save_take(store, current)

        store.save()
        path = takefile.open_take(store, take, episode, scene_obj)
        if takefile.LAST_DROPPED_DRAWINGS:
            self.report({"WARNING"},
                        f"{takefile.LAST_DROPPED_DRAWINGS} "
                        + _("drawing(s) were never saved to the file"))
        foreign = gp.foreign_take_objects(take)
        if foreign:
            self.report({"WARNING"},
                        f"{len(foreign)} " + _("object(s) from another take"))
        self.report({"INFO"}, _("take opened") + f": {take.code} ({path.name})")
        return {"FINISHED"}


class NSB_OT_goto_take(Operator):
    """Entra no take pelo id — é o clique na miniatura do board.

    A lista de takes já entra no take ao mudar a seleção; o board é a mesma
    ordem dita de outro jeito ("este aqui"), então ele não podia exigir dois
    passos. O operador aponta a interface para o take e abre na hora, em vez de
    esperar o timer da lista: quem clicou na miniatura já escolheu.
    """

    bl_idname = "nsb.goto_take"
    bl_label = "Open this take"
    bl_options = {"REGISTER", "INTERNAL"}

    uid: StringProperty(default="")

    @classmethod
    def poll(cls, context):
        return state.has_project()

    def execute(self, context):
        from . import props

        store = state.require_store()
        achado = store.project.find_take(self.uid)
        if achado is None:
            self.report({"ERROR"}, _("this take is not in the project anymore"))
            return {"CANCELLED"}
        episode, scene_obj, take = achado

        st = context.window_manager.nsb
        with props.mirroring():
            st.episode_index = store.project.episodes.index(episode)
            st.scene_index = episode.scenes.index(scene_obj)
            sync.sync_scenes(context)
            st.take_index = scene_obj.takes.index(take)

        if takefile.current_take_of_file(store) is take:
            return {"FINISHED"}
        return bpy.ops.nsb.open_take()


class NSB_OT_save_take(Operator):
    bl_idname = "nsb.save_take"
    bl_label = "Save take"
    bl_description = "Writes the .nuc and updates the take drawing index"

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        return store is not None and takefile.current_take_of_file(store) is not None

    def execute(self, context):
        store = state.require_store()
        take = takefile.current_take_of_file(store)
        path = takefile.save_take(store, take)
        sync.sync_all(context)
        self.report({"INFO"}, f"{len(take.drawings)} " + _("drawing(s) saved to")
                              + f" {path.name}")
        return {"FINISHED"}


class NSB_OT_add_drawing(Operator):
    bl_idname = "nsb.add_drawing"
    bl_label = "New drawing"
    bl_description = "Creates a new keyframe on the content layers and jumps to it"

    frame: IntProperty(default=-1, options={"HIDDEN"})

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        if store is None:
            return False
        take = takefile.current_take_of_file(store)
        return take is not None and gp.find_take_object(take) is not None

    def execute(self, context):
        store = state.require_store()
        take = takefile.current_take_of_file(store)
        ob = gp.find_take_object(take)

        # Ler a tela ANTES: o desenho novo nasce 12 frames à frente do último e
        # essa divergência não é timing do artista — capturá-la depois faria
        # todo take virar tempo fixo já no primeiro desenho.
        takefile.capture_from_scene(context.scene, store, take)

        number = gp.add_drawing_keyframe(ob, None if self.frame < 0 else self.frame)
        gp.sync_drawings_from_gp(take, ob)
        position = gp.drawing_frames(ob).index(number)

        # Um desenho a mais reparte a duração de novo; o cursor segue o que
        # acabou de nascer até o lugar onde ele foi parar.
        takefile.refresh_take_view(context.scene, store, take, capture=False)
        frames = gp.drawing_frames(ob)
        context.scene.frame_set(frames[position] if position < len(frames) else number)

        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("drawing") + f" {len(take.drawings)} @ "
                              f"{context.scene.frame_current}")
        return {"FINISHED"}


class NSB_OT_remove_drawing(Operator):
    bl_idname = "nsb.remove_drawing"
    bl_label = "Remove drawing"
    bl_options = {"REGISTER", "INTERNAL"}

    frame: IntProperty(default=-1)

    @classmethod
    def poll(cls, context):
        return NSB_OT_add_drawing.poll(context)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        store = state.require_store()
        take = takefile.current_take_of_file(store)
        ob = gp.find_take_object(take)
        number = context.scene.frame_current if self.frame < 0 else self.frame

        takefile.capture_from_scene(context.scene, store, take)
        gp.remove_drawing_keyframe(ob, number)
        gp.sync_drawings_from_gp(take, ob)
        takefile.refresh_take_view(context.scene, store, take, capture=False)
        store.save()
        sync.sync_all(context)
        return {"FINISHED"}


class NSB_OT_split_take(Operator):
    """Parte o take em dois no quadro em que o artista está.

    Quem decide onde um take termina é ele: não há regra que adivinhe o corte a
    partir do desenho. O quadro atual vira o PRIMEIRO do take novo, que entra na
    cena logo depois deste; desenhos, falas e tempo vão para o lado certo, e a
    duração somada não muda.
    """

    bl_idname = "nsb.split_take"
    bl_label = "Cut take here"
    bl_description = ("Splits the take in two at the current frame: what comes "
                      "after becomes the next take of the scene")

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        if store is None:
            return False
        take = takefile.current_take_of_file(store)
        return take is not None and gp.find_take_object(take) is not None

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(self, event)

    def execute(self, context):
        import shutil

        from .core import SplitError, split_plan

        store = state.require_store()
        take = takefile.current_take_of_file(store)
        achado = store.project.find_take(take.id)
        if achado is None:
            self.report({"ERROR"}, _("this take is not in the project anymore"))
            return {"CANCELLED"}
        _episodio, cena_do_take, _t = achado

        fps = store.project.settings.fps
        corte = context.scene.frame_current

        # O `.nuc` precisa estar em dia antes de virar dois: o que o artista
        # acabou de desenhar e arrastar entra aqui.
        takefile.save_take(store, take)
        try:
            antes, depois = split_plan(take, corte, fps)
        except SplitError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}

        novo = store.add_take(cena_do_take,
                              store.next_take_code(cena_do_take, take.code),
                              after=take)
        novo.character_ids = list(take.character_ids)
        novo.prop_ids = list(take.prop_ids)

        # O arquivo do take novo nasce como cópia deste — a arte é a mesma, o
        # que muda é o trecho que cada um guarda.
        shutil.copyfile(store.paths.abs(take.file), store.paths.abs(novo.file))

        id_antigo = take.id
        for alvo, plano in ((novo, depois), (take, antes)):
            alvo.drawings = plano.drawings
            alvo.audios = plano.audios
            # O tempo dos dois pedaços já está decidido: deixar em automático
            # faria a duração cair no áudio de cada lado e o corte mudaria a cena.
            alvo.duration_override = plano.frames / float(fps)
        store.save()

        for alvo, inicio, fim in ((novo, corte, corte + depois.frames - 1),
                                  (take, 1, corte - 1)):
            bpy.ops.wm.open_mainfile(filepath=str(store.paths.abs(alvo.file)))
            cena = bpy.context.scene
            objeto = next((o for o in cena.objects
                           if o.type in {"GREASEPENCIL", "GPENCIL"}
                           and o.get(gp.TAKE_KEY) == id_antigo), None)
            if objeto is not None:
                objeto[gp.TAKE_KEY] = alvo.id
                gp.slice_drawings(objeto, inicio, fim)
            gp.rebase_animation(cena, inicio)
            takefile.stamp_scene(cena, store, alvo)
            bpy.ops.wm.save_as_mainfile(filepath=str(store.paths.abs(alvo.file)))

        # O artista fica onde estava, agora só com a primeira parte.
        takefile.open_take(store, take, None, None)
        sync.sync_all(context)
        self.report({"INFO"}, _("take split at frame") + f" {corte}: "
                              f"{take.code} + {novo.code}")
        return {"FINISHED"}


class NSB_OT_goto_drawing(Operator):
    bl_idname = "nsb.goto_drawing"
    bl_label = "Go to drawing"
    bl_options = {"REGISTER", "INTERNAL"}

    frame: IntProperty(default=1)

    def execute(self, context):
        context.scene.frame_set(self.frame)
        return {"FINISHED"}


class NSB_OT_add_character_layer(Operator):
    """Cria a camada de lineart do personagem selecionado na biblioteca.

    A cor hex vem do cadastro — metadado declarado, nunca lido do pixel.
    """

    bl_idname = "nsb.add_character_layer"
    bl_label = "Character layer"

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        if store is None:
            return False
        st = context.window_manager.nsb
        take = takefile.current_take_of_file(store)
        return (take is not None and gp.find_take_object(take) is not None
                and 0 <= st.character_index < len(st.characters))

    def execute(self, context):
        store = state.require_store()
        st = context.window_manager.nsb
        character = store.library.characters[st.character_index]
        take = takefile.current_take_of_file(store)
        ob = gp.find_take_object(take)

        gp.ensure_character_layer(ob, character)
        if character.id not in take.character_ids:
            take.character_ids.append(character.id)
        store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("character layer ready") + f": {character.name} "
                              f"({character.hex_color})")
        return {"FINISHED"}


class NSB_OT_use_character_material(Operator):
    """Prepara o take para desenhar o personagem selecionado na biblioteca.

    O caminho normal é o CLIQUE na lista de personagens, que já faz isto; o
    operador continua existindo para quem abrir o take depois de escolher (a
    seleção estava feita, mas o arquivo era outro) e para atalho de teclado.
    """

    bl_idname = "nsb.use_character_material"
    bl_label = "Draw this character"
    bl_description = ("Gets the take ready to draw this character: his layer "
                      "active and the brush on his colour")

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        if store is None:
            return False
        st = context.window_manager.nsb
        take = takefile.current_take_of_file(store)
        return (take is not None and gp.find_take_object(take) is not None
                and 0 <= st.character_index < len(st.characters))

    def execute(self, context):
        store = state.require_store()
        st = context.window_manager.nsb
        character = store.library.characters[st.character_index]
        take = takefile.current_take_of_file(store)
        ob = gp.find_take_object(take)
        try:
            gp.draw_as_character(context, ob, character)
        except ValueError as exc:  # hex inválido no cadastro
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        if character.id not in take.character_ids:
            take.character_ids.append(character.id)
            store.save()
        sync.sync_all(context)
        self.report({"INFO"}, _("drawing with") + f": {character.name} "
                              f"({character.hex_color})")
        return {"FINISHED"}


class NSB_OT_place_prop(Operator):
    """Traz para o canvas a arte de um prop que já está na biblioteca.

    O caminho de ida existia desde a RF-09 (o desenho vira PNG na biblioteca);
    faltava o de volta, que é o que dá sentido a ter biblioteca: o mesmo objeto
    aparecendo em vários takes sem ser redesenhado. A arte entra como um plano
    do tamanho do quadro — quando o PNG veio do próprio board, ela reaparece
    exatamente onde foi desenhada — e fica gravada no `.nuc` do take.
    """

    bl_idname = "nsb.place_prop"
    bl_label = "Bring prop into the take"
    bl_description = ("Puts the selected prop's art into the take being drawn, "
                      "behind the drawing")

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        if store is None:
            return False
        st = context.window_manager.nsb
        take = takefile.current_take_of_file(store)
        return (take is not None and gp.find_take_object(take) is not None
                and 0 <= st.prop_index < len(st.props))

    def execute(self, context):
        store = state.require_store()
        st = context.window_manager.nsb
        prop = store.library.props[st.prop_index]
        take = takefile.current_take_of_file(store)

        # RN04: um prop provisório já substituído entra na versão FINAL — o take
        # que o usa não deveria mostrar arte velha só porque foi montado antes.
        final = store.library.resolve_prop(prop.id) or prop
        if not final.file:
            self.report({"ERROR"}, _("this prop has no art yet"))
            return {"CANCELLED"}
        art = store.paths.abs(final.file)
        if not art.is_file():
            self.report({"ERROR"}, _("the prop art is missing") + f": {final.file}")
            return {"CANCELLED"}

        ob, novo = gp.place_prop(context.scene, final, art)
        if prop.id not in take.prop_ids:
            take.prop_ids.append(prop.id)
        store.save()
        sync.sync_all(context)

        if novo:
            self.report({"INFO"}, _("prop brought into the take") + f": {ob.name}")
        else:
            self.report({"INFO"}, _("prop art updated") + f": {ob.name}")
        return {"FINISHED"}


class NSB_OT_fix_bg_grayscale(Operator):
    """RN02: converte para luminância tudo que escapou de cinza no BG."""

    bl_idname = "nsb.fix_bg_grayscale"
    bl_label = "Convert background to gray"

    @classmethod
    def poll(cls, context):
        return NSB_OT_add_drawing.poll(context)

    def execute(self, context):
        store = state.require_store()
        take = takefile.current_take_of_file(store)
        ob = gp.find_take_object(take)
        fixed = gp.enforce_bg_grayscale(ob)
        if fixed:
            self.report({"INFO"}, f"{fixed} " + _("background color(s) turned gray"))
        else:
            self.report({"INFO"}, _("background was already grayscale"))
        return {"FINISHED"}


class NSB_OT_clean_foreign(Operator):
    bl_idname = "nsb.clean_foreign"
    bl_label = "Remove other takes' art"
    bl_description = ("Removes Grease Pencil objects of OTHER takes left inside "
                      "this file; objects with drawings are kept")

    @classmethod
    def poll(cls, context):
        store = state.get_store()
        if store is None:
            return False
        take = takefile.current_take_of_file(store)
        return take is not None and bool(gp.foreign_take_objects(take))

    def execute(self, context):
        store = state.require_store()
        take = takefile.current_take_of_file(store)

        removed, kept = 0, 0
        for ob in gp.foreign_take_objects(take):
            # Objeto com traço pode ser a ÚNICA cópia da arte daquele take:
            # apagar seria perda irreversível, então só some o que está vazio.
            if gp.has_art(ob):
                kept += 1
                continue
            bpy.data.objects.remove(ob, do_unlink=True)
            removed += 1

        if kept:
            self.report({"WARNING"},
                        f"{removed} " + _("object(s) removed") + f", {kept} "
                        + _("kept because they have drawings"))
        else:
            self.report({"INFO"}, f"{removed} " + _("object(s) removed"))
        return {"FINISHED"}


CLASSES = (
    NSB_OT_open_take, NSB_OT_goto_take, NSB_OT_save_take, NSB_OT_clean_foreign,
    NSB_OT_add_drawing, NSB_OT_remove_drawing, NSB_OT_goto_drawing,
    NSB_OT_split_take,
    NSB_OT_add_character_layer, NSB_OT_use_character_material,
    NSB_OT_place_prop,
    NSB_OT_fix_bg_grayscale,
)


def register():
    apply_context(CLASSES)
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
