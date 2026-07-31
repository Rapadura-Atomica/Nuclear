"""Entremeio — assistente local de in-betweening para o Nuclear (fork Blender 5.0).

Marco A: esqueleto carregável + ponte de LEITURA do rig (read_rig). Sem engine
de geração ainda (Marco B). O painel apenas lê o PegRig ativo e reporta a
estrutura — prova que a ponte enxerga pegs, hierarquia e âncoras.

Ver SPEC_Fase0.md (§4, §9) e PRD_Entremeio_v0.5 (RF-8.3).
"""

bl_info = {
    "name": "Entremeio",
    "author": "Rapadura Atômica",
    "version": (0, 1, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > Entremeio",
    "description": "In-betweening fiel ao animatic no espaço das Pegs (local, determinístico).",
    "category": "Animation",
}

import os
import sys
import time

import bpy

from . import ir, rig_bridge, fidelity, discrete, report as report_mod
from .engine import BaselineEngine, BaselineParams, SplineEngine, SplineParams
from .engine import ipc as ipc_engine
from .engine.ipc import IPCEngine, IPCParams, IPCError, reference_worker_path

_ADDON_DIR = os.path.dirname(__file__)


def _report_dir(props):
    """Diretório do relatório: prop, senão ao lado do .blend, senão temp."""
    if props.report_dir.strip():
        return bpy.path.abspath(props.report_dir.strip())
    blend = bpy.data.filepath
    if blend:
        return os.path.join(os.path.dirname(blend), "entremeio_reports")
    return os.path.join(bpy.app.tempdir or "/tmp", "entremeio_reports")


# --------------------------------------------------------------------------
# Operador: ler o rig ativo e reportar (Marco A)
# --------------------------------------------------------------------------
class ENTREMEIO_OT_read_rig(bpy.types.Operator):
    bl_idname = "entremeio.read_rig"
    bl_label = "Ler Rig (Entremeio)"
    bl_description = "Lê o PegRig selecionado e reporta pegs, hierarquia e âncoras"
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.entremeio
        target = props.rig_name.strip() or None

        # fallback: primeiro PegRig da cena, se nenhum nome informado
        if target is None:
            escolhido = rig_bridge.pick_default_rig()
            if escolhido is None:
                self.report({"ERROR"}, "Nenhum PegRig na cena.")
                return {"CANCELLED"}
            target = escolhido.name

        try:
            plan = rig_bridge.read_rig(target, seed=props.seed)
        except ValueError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        n_pegs = len(plan.tracks)
        n_anchored = sum(1 for t in plan.tracks if t.anchors)
        total_anchors = sum(len(t.anchors) for t in plan.tracks)
        uses_squash = any(
            c.startswith("squash") or c == "use_squash"
            for t in plan.tracks for c in t.animated_channels()
        )
        # detecção do trecho: onde a animação começa e termina (campos editáveis)
        span = plan.anchors_span()
        span_note = ""
        if span is not None:
            if props.auto_range:
                props.frame_start, props.frame_end = span
            span_note = f" · animação detectada em {span[0]}–{span[1]}"
        self.report(
            {"INFO"},
            f"Entremeio: '{target}' — {n_pegs} pegs, {n_anchored} com âncoras, "
            f"{total_anchors} keyframes-âncora ({plan.frame_start}-{plan.frame_end} @ {plan.fps:.3g}fps)"
            + (" · squash detectado" if uses_squash else "") + span_note,
        )
        # detalhe no console para inspeção durante o desenvolvimento
        print(f"[Entremeio] read_rig('{target}'):")
        for t in plan.tracks:
            frames = [k.frame for k in t.anchors]
            chans = ", ".join(sorted(t.animated_channels())) or "(sem keys)"
            print(f"   peg '{t.name}' (parent={t.peg.parent}) âncoras={frames} canais=[{chans}]")
        return {"FINISHED"}


# --------------------------------------------------------------------------
# Operador: detectar o trecho (onde a animação começa e termina)
# --------------------------------------------------------------------------
class ENTREMEIO_OT_detect_range(bpy.types.Operator):
    bl_idname = "entremeio.detect_range"
    bl_label = "Detectar Trecho (Entremeio)"
    bl_description = ("Detecta onde a animação começa e termina (primeira e última "
                      "pose-chave, no escopo atual) e preenche Início/Fim — edite à vontade")
    bl_options = {"REGISTER"}

    def execute(self, context):
        props = context.scene.entremeio
        target = props.rig_name.strip() or getattr(rig_bridge.pick_default_rig(), "name", None)
        if target is None:
            self.report({"ERROR"}, "Nenhum PegRig na cena.")
            return {"CANCELLED"}
        try:
            plan = rig_bridge.read_rig(target, seed=props.seed)
        except (KeyError, ValueError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}
        if props.scope == "SUBTREE" and props.scope_peg.strip():
            names = plan.subtree_names(props.scope_peg.strip())
            if not names:
                self.report({"ERROR"}, f"Peg '{props.scope_peg}' não encontrada no rig.")
                return {"CANCELLED"}
            plan = plan.scoped_to(names)
        span = plan.anchors_span()
        if span is None:
            self.report({"WARNING"}, "Nenhuma pose-chave encontrada — nada a detectar.")
            return {"CANCELLED"}
        props.frame_start, props.frame_end = span
        self.report({"INFO"}, f"Trecho detectado: {span[0]}–{span[1]} (edite Início/Fim se quiser)")
        return {"FINISHED"}


# --------------------------------------------------------------------------
# Operador: gerar in-betweens (Marco B) — read -> generate -> validate -> write
# --------------------------------------------------------------------------
class ENTREMEIO_OT_generate(bpy.types.Operator):
    bl_idname = "entremeio.generate"
    bl_label = "Gerar In-betweens (Entremeio)"
    bl_description = "Gera o movimento entre as poses-chave do rig, no espaço das pegs"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        props = context.scene.entremeio
        target = props.rig_name.strip() or getattr(rig_bridge.pick_default_rig(), "name", None)
        if target is None:
            self.report({"ERROR"}, "Nenhum PegRig na cena.")
            return {"CANCELLED"}

        try:
            rig = bpy.data.pegrigs[target]
        except KeyError as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        # RF-8.6: valida a compatibilidade da API antes de mexer no rig
        compat_ok, issues = rig_bridge.check_compatibility(rig)
        if not compat_ok:
            self.report({"ERROR"}, f"Entremeio incompatível com este rig/build: {issues[0]}")
            return {"CANCELLED"}

        try:
            plan = rig_bridge.read_rig(target, seed=props.seed)
        except (KeyError, ValueError) as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        # RF-5.3: refino cirúrgico — limitar a uma peg + sub-árvore
        scope_names = None
        if props.scope == "SUBTREE" and props.scope_peg.strip():
            scope_names = plan.subtree_names(props.scope_peg.strip())
            if not scope_names:
                self.report({"ERROR"}, f"Peg '{props.scope_peg}' não encontrada no rig.")
                return {"CANCELLED"}

        # Trecho: janela de frames a ler/gerar — detectada pelas âncoras ou manual
        manual_range = None
        if not props.auto_range:
            if props.frame_end <= props.frame_start:
                self.report({"ERROR"},
                            f"Trecho inválido: Fim ({props.frame_end}) deve ser maior "
                            f"que Início ({props.frame_start}).")
                return {"CANCELLED"}
            manual_range = (props.frame_start, props.frame_end)

        # regeneração limpa (só do escopo/trecho, se houver): remove o que o Entremeio gerou antes.
        # Na janela manual, limpa SÓ o que dá pra regenerar (>=2 âncoras dentro da janela) —
        # limpar além disso abriria buraco em vãos cujas âncoras estão fora do trecho.
        if manual_range is None:
            rig_bridge.clear_generated(rig, pegs=scope_names)
        else:
            regen = rig_bridge.regenerable_in_range(rig, manual_range, pegs=scope_names)
            rig_bridge.clear_generated(rig, pegs=scope_names, frame_range=manual_range,
                                       peg_channels=regen)
        plan = rig_bridge.read_rig(target, seed=props.seed)   # âncoras limpas
        if scope_names is not None:
            plan = plan.scoped_to(scope_names)

        if manual_range is not None:
            plan = plan.clipped(*manual_range)
        else:
            span = plan.anchors_span()
            if span is not None:
                plan = plan.clipped(*span)
                # mostra o trecho detectado nos campos (editáveis com "Detectar trecho" desligado)
                props.frame_start, props.frame_end = span

        if props.engine_mode == "IPC":
            # motor externo (Fase 1): worker em processo separado. Default = worker de
            # referência (spline); aponte ipc_python p/ o venv de IA e ipc_worker p/ o
            # worker PyTorch p/ usar o modelo treinado.
            python_exe = props.ipc_python.strip() or sys.executable
            worker_script = props.ipc_worker.strip() or reference_worker_path(_ADDON_DIR)
            engine = IPCEngine(
                [python_exe, worker_script], _ADDON_DIR,
                IPCParams(engine="spline", tension=props.tension,
                          overlap=props.overlap, style=props.style, step=props.step))
        elif props.engine_mode == "SPLINE":
            engine = SplineEngine(SplineParams(tension=props.tension, overlap=props.overlap, step=props.step))
        else:
            engine = BaselineEngine(BaselineParams(ease=props.ease, overshoot=props.overshoot, step=props.step))

        _t = time.perf_counter()
        try:
            generated = engine.generate(plan)
        except IPCError as e:
            self.report({"ERROR"}, f"Motor externo (IPC): {e}")
            return {"CANCELLED"}
        t_generate = (time.perf_counter() - _t) * 1000.0

        # GUARDA-CORPOS antes de escrever (P1/P2): rejeita o lote inteiro se ferir.
        report = fidelity.validate(plan, generated)
        if not report.ok:
            self.report({"ERROR"}, f"Entremeio rejeitou a geração — {report.summary()}")
            for v in report.violations[:5]:
                print(f"[Entremeio] VIOLAÇÃO {v.rule}: {v.peg} f{v.frame} {v.channel} — {v.detail}")
            return {"CANCELLED"}

        if generated.frame_count() == 0:
            # distingue "não há vão" de "o passo não cabe no vão" — com Passo 2 e um
            # vão de 2 frames não cabe in-between nenhum, e culpar as poses confunde.
            maior_vao = 0
            for t in plan.tracks:
                fr = sorted(k.frame for k in t.anchors)
                maior_vao = max([maior_vao] + [b - a for a, b in zip(fr, fr[1:])])
            if maior_vao > 1 and props.step >= maior_vao:
                self.report({"WARNING"},
                            f"Nada a gerar: o Passo ({props.step}) não cabe no maior vão "
                            f"entre poses ({maior_vao} frames) — reduza o Passo.")
            else:
                self.report({"WARNING"},
                            "Nada a gerar: nenhuma peg tem âncoras com vão entre elas"
                            f" no trecho {plan.frame_start}–{plan.frame_end}.")
            return {"CANCELLED"}

        # snapshot das exposições GP ANTES (RF-4.6): provar que a geração não as toca
        exposure_before = discrete.snapshot_gp_exposure(rig)
        # drift de linha de base: mede ANTES de gerar, para só alarmar quando a
        # geração PIORA o quadro. Drift alto já na linha de base costuma ser rig
        # que o depsgraph não avalia (cópia órfã do PegRig, sem objeto preso).
        drift_before, _ = rig_bridge.measure_fidelity(rig, plan)
        seguidores = rig_bridge.followers_of(rig)

        # identidade do que JÁ estava registrado antes desta chamada — o diff depois
        # é exatamente o que ELA escreveu, e é só isso que um revert pode desfazer
        # sem tocar em gerações anteriores (mesmo mecanismo do descarte da Prévia).
        rec_antes_ids = {(e[0], e[1], e[2]) for e in rig_bridge._load_record(rig)}

        _t = time.perf_counter()
        inserted = rig_bridge.write_keys(rig, generated)
        t_write = (time.perf_counter() - _t) * 1000.0
        rig_bridge.record_generated(
            rig, generated,
            merge=(scope_names is not None or manual_range is not None))
        max_drift, offenders = rig_bridge.measure_fidelity(rig, plan)
        exposure_ok, changes = discrete.verify_exposure_preserved(rig, exposure_before)

        def _revert_this_write():
            # P1/P2 são invioláveis: se algo escapou do guarda-corpos pré-escrita e
            # feriu uma âncora/exposição de verdade, desfaz — nunca fica só no aviso.
            novas = [e for e in rig_bridge._load_record(rig)
                    if (e[0], e[1], e[2]) not in rec_antes_ids]
            rig_bridge.clear_generated_entries(rig, novas)

        if not exposure_ok:
            _revert_this_write()
            self.report({"ERROR"},
                        f"Entremeio rejeitou e desfez a geração — exposição de camada GP "
                        f"foi alterada ({len(changes)}), violação de RF-4.6.")
            for c in changes[:5]:
                print(f"[Entremeio] EXPOSIÇÃO MUDOU: {c}")
            return {"CANCELLED"}

        if offenders and max_drift > drift_before + 1e-4:
            _revert_this_write()
            self.report({"ERROR"},
                        f"Entremeio rejeitou e desfez a geração — drift AUMENTOU em "
                        f"{len(offenders)} âncora(s) ({drift_before:.2g} → {max_drift:.2g}).")
            return {"CANCELLED"}
        # RF-6.5 / RF-9.4: relatório auditável versionável (params, seed, modelo, drift, aderência)
        report_note = ""
        if props.save_report:
            engine_info = {
                "mode": props.engine_mode,
                "model_version": getattr(engine, "last_model_version", props.engine_mode.lower()),
                "params": ({"tension": props.tension, "overlap": props.overlap,
                            "style": props.style, "step": props.step}
                           if props.engine_mode != "EASE"
                           else {"ease": props.ease, "overshoot": props.overshoot, "step": props.step}),
            }
            audit = report_mod.build_report(
                rig_name=target, plan=plan, generated=generated, engine=engine_info,
                seed=props.seed, fidelity_report=report, drift_max=max_drift,
                drift_offenders=offenders, exposure_ok=exposure_ok,
                keyframes_inserted=inserted,
                timing_ms={"generate": round(t_generate, 2), "write": round(t_write, 2)},
                timestamp=time.strftime("%Y-%m-%dT%H%M%S"))
            try:
                jpath, _ = report_mod.write_report(audit, _report_dir(props))
                report_note = f" · relatório: {os.path.basename(jpath)}"
                print("[Entremeio] relatório:\n" + report_mod.summarize(audit))
            except OSError as e:
                report_note = " · (falha ao salvar relatório)"
                print(f"[Entremeio] erro ao salvar relatório: {e}")

        if not seguidores:
            # keyframes entram, mas nada na cena se mexe: é o sintoma clássico de
            # gerar na cópia órfã do rig (take com `nome` e `nome.001`).
            outros = [r.name for r in bpy.data.pegrigs
                      if r != rig and rig_bridge.followers_of(r)]
            dica = f" Use '{outros[0]}'." if outros else ""
            self.report({"WARNING"},
                        f"{inserted} keys geradas, mas NENHUM objeto segue '{rig.name}' — "
                        f"nada vai se mover na tela.{dica}")
        elif offenders:
            self.report({"INFO"},
                        f"Entremeio: {inserted} keys · trecho {plan.frame_start}–{plan.frame_end} · "
                        f"{report.summary()} · drift pré-existente={max_drift:.1g} "
                        f"(já estava lá antes de gerar) · exposição preservada{report_note}")
        else:
            self.report({"INFO"},
                        f"Entremeio: {inserted} keys · trecho {plan.frame_start}–{plan.frame_end} · "
                        f"{report.summary()} · drift={max_drift:.1g} · exposição preservada{report_note}")
        return {"FINISHED"}


# --------------------------------------------------------------------------
# Operador: Prever (modal) — gera, toca em loop, ENTER aplica / ESC descarta (RF-7.4)
# --------------------------------------------------------------------------
class ENTREMEIO_OT_preview(bpy.types.Operator):
    bl_idname = "entremeio.preview"
    bl_label = "Prever (Entremeio)"
    bl_description = "Gera e toca o trecho em loop; ENTER aplica, ESC descarta (não comita até aplicar)"
    bl_options = {"REGISTER"}

    def _span(self, rig):
        lo = hi = None
        for fcu in rig_bridge._iter_fcurves(rig.animation_data):
            if rig_bridge.parse_peg_data_path(fcu.data_path):
                for kp in fcu.keyframe_points:
                    f = int(round(kp.co[0]))
                    lo = f if lo is None else min(lo, f)
                    hi = f if hi is None else max(hi, f)
        return lo, hi

    def _stop(self, context):
        if context.screen and context.screen.is_animation_playing:
            try:
                bpy.ops.screen.animation_cancel(restore_frame=False)
            except RuntimeError:
                pass

    def invoke(self, context, event):
        props = context.scene.entremeio
        rig = bpy.data.pegrigs.get(props.rig_name) or rig_bridge.pick_default_rig()
        if rig is None:
            self.report({"ERROR"}, "Nenhum PegRig na cena.")
            return {"CANCELLED"}
        self._rig_name = rig.name

        # gera (prévia não salva relatório — é efêmera; use Gerar p/ registrar)
        prev_save = props.save_report
        props.save_report = False
        # diff por IDENTIDADE (peg, canal, frame) — o registro guarda também o valor
        # (list, não-hasheável), então não dá pra jogar a entrada inteira num set.
        rec_antes_ids = {(e[0], e[1], e[2]) for e in rig_bridge._load_record(rig)}
        try:
            res = bpy.ops.entremeio.generate("EXEC_DEFAULT")
        finally:
            props.save_report = prev_save
        if "FINISHED" not in res:
            return {"CANCELLED"}   # o generate já reportou o motivo

        rig = bpy.data.pegrigs.get(self._rig_name)
        # o que ESTA geração escreveu (diff do registro) — é só isso que o ESC descarta
        self._new_entries = [e for e in rig_bridge._load_record(rig)
                             if (e[0], e[1], e[2]) not in rec_antes_ids]

        lo, hi = self._span(rig)
        # o trecho ativo (detectado/manual) manda no loop da prévia
        if props.frame_end > props.frame_start:
            lo, hi = props.frame_start, props.frame_end
        if lo is not None:
            scene = context.scene
            scene.use_preview_range = True
            scene.frame_preview_start = lo
            scene.frame_preview_end = hi
            scene.frame_set(lo)
            try:
                bpy.ops.screen.animation_play()
            except RuntimeError:
                pass

        context.window_manager.modal_handler_add(self)
        self.report({"INFO"}, "Prévia — ENTER aplica · ESC descarta")
        return {"RUNNING_MODAL"}

    def modal(self, context, event):
        if event.type in {"ESC", "RIGHTMOUSE"}:
            self._stop(context)
            # descarte DETERMINÍSTICO: remove o que ESTA prévia gerou (volta às âncoras).
            # (undo não serve: não captura mudanças via keyframe_insert da API de dados.)
            # Gerações aplicadas antes — outras janelas/escopos — ficam intactas.
            rig = bpy.data.pegrigs.get(self._rig_name)
            if rig is not None:
                rig_bridge.clear_generated_entries(rig, self._new_entries)
            context.scene.frame_set(context.scene.frame_preview_start)
            if context.area:
                context.area.tag_redraw()
            self.report({"INFO"}, "Prévia descartada — voltou às suas poses")
            return {"CANCELLED"}
        if event.type in {"RET", "NUMPAD_ENTER"} and event.value == "PRESS":
            self._stop(context)
            self.report({"INFO"}, "Prévia aplicada")
            return {"FINISHED"}
        return {"PASS_THROUGH"}


# --------------------------------------------------------------------------
# Propriedades da cena
# --------------------------------------------------------------------------
class ENTREMEIO_PG_settings(bpy.types.PropertyGroup):
    rig_name: bpy.props.StringProperty(
        name="Rig",
        description="Nome do PegRig a ler (vazio = primeiro da cena)",
        default="",
    )
    seed: bpy.props.IntProperty(
        name="Seed",
        description="Semente determinística da geração (RF-4.4)",
        default=0,
        min=0,
    )
    auto_range: bpy.props.BoolProperty(
        name="Detectar trecho",
        description="Detecta onde a animação começa e termina (primeira e última pose-chave) "
                    "a cada geração e preenche Início/Fim; desligue para digitar o trecho na mão",
        default=True,
    )
    frame_start: bpy.props.IntProperty(
        name="Início",
        description="Primeiro frame do trecho a ler/gerar; poses fora do trecho ficam intactas",
        default=1,
    )
    frame_end: bpy.props.IntProperty(
        name="Fim",
        description="Último frame do trecho a ler/gerar; poses fora do trecho ficam intactas",
        default=1,
    )
    step: bpy.props.IntProperty(
        name="Passo",
        description="Densidade dos in-betweens: 1 = keyframe em todo frame; 2 = a cada 2 frames (\"nos dois\")... até 5",
        default=1, min=1, max=5,
    )
    scope: bpy.props.EnumProperty(
        name="Escopo",
        description="Refino cirúrgico: gerar o rig todo ou só uma peg + sua sub-árvore (RF-5.3)",
        items=[
            ("ALL", "Rig todo", "Gera para todas as pegs com âncoras"),
            ("SUBTREE", "Peg + sub-árvore", "Gera só a peg escolhida e seus descendentes; o resto fica intacto"),
        ],
        default="ALL",
    )
    scope_peg: bpy.props.StringProperty(
        name="Peg raiz",
        description="Peg cujo sub-árvore será (re)gerado (ex.: o Master Peg do braço)",
        default="",
    )
    engine_mode: bpy.props.EnumProperty(
        name="Modo",
        description="Motor de geração dos in-betweens",
        items=[
            ("SPLINE", "Spline (flui)", "Hermite/Catmull-Rom: flui pelas poses sem parar (C1). Recomendado p/ 3+ poses"),
            ("EASE", "Ease (pairwise)", "Ease-in/out entre cada par de âncoras (para em cada pose)"),
            ("IPC", "Motor externo (IA)", "Gera via processo separado (fronteira IPC). Default = worker de referência"),
        ],
        default="SPLINE",
    )
    ipc_python: bpy.props.StringProperty(
        name="Python do motor",
        description="Executável Python do venv do motor de IA (vazio = Python do host)",
        default="", subtype="FILE_PATH",
    )
    ipc_worker: bpy.props.StringProperty(
        name="Worker",
        description="Script do worker do motor (vazio = worker de referência que roda o spline)",
        default="", subtype="FILE_PATH",
    )
    style: bpy.props.FloatProperty(
        name="Estilo",
        description="Motor de IA: intensidade do 'sotaque' de movimento (antecipação/overshoot aprendidos)",
        default=0.6, min=0.0, max=1.0,
    )
    save_report: bpy.props.BoolProperty(
        name="Salvar relatório",
        description="Grava relatório auditável (params, seed, modelo, drift, aderência) a cada geração (RF-6.5)",
        default=True,
    )
    report_dir: bpy.props.StringProperty(
        name="Pasta do relatório",
        description="Onde salvar (vazio = ao lado do .blend, em entremeio_reports/)",
        default="", subtype="DIR_PATH",
    )
    ease: bpy.props.FloatProperty(
        name="Ease",
        description="0 = linear; 1 = ease-in-out cheio (distribui o spacing)",
        default=0.6, min=0.0, max=1.0,
    )
    overshoot: bpy.props.FloatProperty(
        name="Overshoot",
        description="Amplitude de overshoot pseudo-aleatório por segmento (zera nas âncoras)",
        default=0.0, min=0.0, max=1.0,
    )
    tension: bpy.props.FloatProperty(
        name="Tensão",
        description="Spline: 0 = flui bastante (Catmull-Rom); 1 = tangentes nulas (mais reto)",
        default=0.0, min=0.0, max=1.0,
    )
    overlap: bpy.props.FloatProperty(
        name="Overlap",
        description="Follow-through: pegs mais fundas na hierarquia arrastam (casaco/cabelo trailing). Não fere âncoras",
        default=0.0, min=0.0, max=1.0,
    )


# --------------------------------------------------------------------------
# Painel
# --------------------------------------------------------------------------
class ENTREMEIO_PT_panel(bpy.types.Panel):
    bl_label = "Entremeio"
    bl_idname = "ENTREMEIO_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Entremeio"

    def draw(self, context):
        layout = self.layout
        props = context.scene.entremeio
        layout.prop_search(props, "rig_name", bpy.data, "pegrigs", text="Rig")
        layout.operator(ENTREMEIO_OT_read_rig.bl_idname, icon="HOOK")

        layout.prop(props, "engine_mode", text="Modo")
        col = layout.column(align=True)
        col.prop(props, "step")
        col.prop(props, "seed")
        if props.engine_mode == "IPC":
            col.prop(props, "style")
            col.prop(props, "ipc_python")
            col.prop(props, "ipc_worker")
        elif props.engine_mode == "SPLINE":
            col.prop(props, "tension")
            col.prop(props, "overlap")
        else:
            col.prop(props, "ease")
            col.prop(props, "overshoot")
        _rig = bpy.data.pegrigs.get(props.rig_name) or rig_bridge.pick_default_rig()
        sc = layout.column(align=True)
        sc.prop(props, "scope", text="Escopo")
        if props.scope == "SUBTREE":
            if _rig:
                sc.prop_search(props, "scope_peg", _rig, "pegs", text="Peg raiz")
            else:
                sc.prop(props, "scope_peg", text="Peg raiz")

        rng = layout.column(align=True)
        rng.prop(props, "auto_range")
        row = rng.row(align=True)
        row.enabled = not props.auto_range
        row.prop(props, "frame_start")
        row.prop(props, "frame_end")
        if not props.auto_range:
            rng.operator(ENTREMEIO_OT_detect_range.bl_idname,
                         icon="ZOOM_SELECTED", text="Detectar do rig")

        rep = layout.column(align=True)
        rep.prop(props, "save_report")
        if props.save_report:
            rep.prop(props, "report_dir")
        row = layout.row(align=True)
        row.operator(ENTREMEIO_OT_generate.bl_idname, icon="TRACKING", text="Gerar In-betweens")
        row.operator(ENTREMEIO_OT_preview.bl_idname, icon="PLAY", text="Prever")


classes = (
    ENTREMEIO_PG_settings,
    ENTREMEIO_OT_read_rig,
    ENTREMEIO_OT_detect_range,
    ENTREMEIO_OT_generate,
    ENTREMEIO_OT_preview,
    ENTREMEIO_PT_panel,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.entremeio = bpy.props.PointerProperty(type=ENTREMEIO_PG_settings)


def unregister():
    del bpy.types.Scene.entremeio
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
