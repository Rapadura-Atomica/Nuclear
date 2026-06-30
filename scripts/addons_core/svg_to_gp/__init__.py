# SPDX-License-Identifier: GPL-2.0-or-later
"""
SVG -> Grease Pencil (helper)

Envelopa o importador nativo do Nuclear (wm.grease_pencil_import_svg) e adiciona
pos-processamento pensado pro pipeline (auto-patch / DPE):

  - 1-clique + lote: importa um ou varios .svg de uma vez (offset em grade).
  - Preserva estrutura: o importador nativo ja vira <g id> em camadas; mantemos.
  - Separa linha/fill: quebra cada material 'Both' em traco-linha + traco-fill e
    poe linha e fill em CAMADAS separadas (dentro de um grupo por camada de origem),
    pronto pro auto-patch que exige linha e fill separados.
  - Escala/posicao: recentra na origem e normaliza o tamanho (altura alvo).

Sem recompilar o Nuclear: tudo via API Python de GP v3.
"""

bl_info = {
    "name": "SVG -> Grease Pencil (helper)",
    "author": "Rapadura Atomica",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "location": "View3D > Sidebar > SVG→GP  |  File > Import/Export",
    "description": "Importa/exporta SVG como Grease Pencil com separacao linha/fill, lote e normalizacao",
    "support": 'COMMUNITY',
    "category": "Import-Export",
}

import os
import math
import bpy
from mathutils import Vector
from bpy.props import (StringProperty, BoolProperty, FloatProperty, IntProperty,
                       EnumProperty, CollectionProperty)
from bpy.types import Operator, Panel, OperatorFileListElement
from bpy_extras.io_utils import ImportHelper, ExportHelper

LINE_MAT = "GP Linha"
FILL_MAT = "GP Fill"


# ------------------------------------------------------------------ materiais
def _ensure_gp_material(name, show_fill, show_stroke):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name)
    if m.grease_pencil is None:
        bpy.data.materials.create_gpencil_data(m)
    g = m.grease_pencil
    g.show_fill = show_fill
    g.show_stroke = show_stroke
    # base branca: a cor real vem dos atributos do stroke (fill_color/vertex_color)
    g.color = (1.0, 1.0, 1.0, 1.0)
    g.fill_color = (1.0, 1.0, 1.0, 1.0)
    return m


def _ensure_split_materials(gp_data):
    """Garante os materiais canonicos Linha/Fill nos slots do objeto. Retorna (line_idx, fill_idx)."""
    line_m = _ensure_gp_material(LINE_MAT, show_fill=False, show_stroke=True)
    fill_m = _ensure_gp_material(FILL_MAT, show_fill=True, show_stroke=False)
    names = [s.name for s in gp_data.materials]
    if LINE_MAT not in names:
        gp_data.materials.append(line_m)
    if FILL_MAT not in names:
        gp_data.materials.append(fill_m)
    return gp_data.materials.find(LINE_MAT), gp_data.materials.find(FILL_MAT)


def _classify(gp_data, stroke):
    """(tem_fill, tem_linha) a partir dos flags do material do stroke."""
    mat = gp_data.materials[stroke.material_index] if stroke.material_index < len(gp_data.materials) else None
    g = mat.grease_pencil if (mat and mat.grease_pencil) else None
    if g is None:
        return True, True
    return bool(g.show_fill), bool(g.show_stroke)


# ------------------------------------------------------ copia (bezier -> poly)
def _bezier_segment(p0, hr0, hl1, p1, res):
    """Pontos de um segmento bezier cubico (t=0..res-1, exclui o ponto final)."""
    out = []
    for s in range(res):
        t = s / res
        u = 1.0 - t
        a, b, c, e = u * u * u, 3.0 * u * u * t, 3.0 * u * t * t, t * t * t
        out.append((a * p0[0] + b * hr0[0] + c * hl1[0] + e * p1[0],
                    a * p0[1] + b * hr0[1] + c * hl1[1] + e * p1[1],
                    a * p0[2] + b * hr0[2] + c * hl1[2] + e * p1[2]))
    return out


def _sample_stroke(ss, res):
    """Amostra um stroke (bezier -> poly). Retorna (positions, src_idx_por_ponto).

    src_idx mapeia cada ponto amostrado ao ponto de controle de origem (herda raio/cor).
    Strokes nao-bezier sao copiados 1:1.
    """
    pts = ss.points
    n = len(pts)
    if ss.curve_type != 2 or n < 2:
        return [tuple(p.position) for p in pts], list(range(n))

    pos = [tuple(p.position) for p in pts]
    hr = [tuple(p.handle_right.position) for p in pts]
    hl = [tuple(p.handle_left.position) for p in pts]
    positions, src_idx = [], []
    seg_count = n if ss.cyclic else (n - 1)
    for i in range(seg_count):
        j = (i + 1) % n
        positions.extend(_bezier_segment(pos[i], hr[i], hl[j], pos[j], res))
        src_idx.extend([i] * res)
    if not ss.cyclic:
        positions.append(pos[-1])
        src_idx.append(n - 1)

    # remove pontos consecutivos coincidentes (pontos de controle duplicados do
    # SVG geram segmentos de comprimento zero -> pontos empilhados inuteis)
    eps = 1e-5
    dp, ds = [], []
    for p, s in zip(positions, src_idx):
        if dp:
            q = dp[-1]
            if abs(p[0] - q[0]) < eps and abs(p[1] - q[1]) < eps and abs(p[2] - q[2]) < eps:
                continue
        dp.append(p)
        ds.append(s)
    return dp, ds


def _copy_strokes(src_dr, idxs, dst_dr, mat_idx, res=12):
    """Copia strokes para dst como POLY amostrado, forcando o material.

    Pegadinha GP v3 (cravada no teste ao vivo): bezier criada via add_strokes +
    edicao de atributos NAO e subdividida no display (renderiza reta entre os
    pontos de controle), e os operadores de edit (material_select) chegam a
    CRASHAR este build. Solucao: amostrar a bezier em pontos poly aqui no Python
    -> sempre renderiza, deterministico, sem operador, seguro em lote/headless.
    """
    if not idxs:
        return
    src = src_dr.strokes
    samples = [_sample_stroke(src[i], res) for i in idxs]
    counts = [len(s[0]) for s in samples]
    if not any(counts):
        return
    sbase = len(dst_dr.strokes)
    dst_dr.add_strokes(counts)

    for k, si in enumerate(idxs):
        ss = src[si]
        ds = dst_dr.strokes[sbase + k]
        positions, src_idx = samples[k]
        try:
            ds.cyclic = ss.cyclic
        except Exception:
            pass
        ds.material_index = mat_idx
        try:
            ds.fill_color = ss.fill_color
            ds.fill_opacity = ss.fill_opacity
        except Exception:
            pass
        sp_list = ss.points
        for j, co in enumerate(positions):
            sp = sp_list[src_idx[j]]
            dp = ds.points[j]
            dp.position = co
            dp.radius = sp.radius
            dp.opacity = sp.opacity
            dp.vertex_color = sp.vertex_color

    if hasattr(dst_dr, 'tag_positions_changed'):
        try:
            dst_dr.tag_positions_changed()
        except Exception:
            pass


# ------------------------------------------------------------------ split L/F
def _split_line_fill(gp_obj, use_groups):
    d = gp_obj.data
    line_idx, fill_idx = _ensure_split_materials(d)

    # Processa de baixo (idx 0) pra cima e move cada resultado pro topo:
    # isso reconstroi a ordem de desenho original (fill atras, linha na frente)
    # e evita o fill cobrir camadas de cima.
    src_layers = list(d.layers)
    for L in src_layers:
        if not len(L.frames):
            d.layers.move_top(L)
            continue
        frame = L.frames[0]
        fno = frame.frame_number
        sdr = frame.drawing

        fill_ids, line_ids = [], []
        for i, s in enumerate(sdr.strokes):
            hf, hl = _classify(d, s)
            if hf:
                fill_ids.append(i)
            if hl:
                line_ids.append(i)

        # so divide se houver os dois tipos; senao so reposiciona no topo
        if not fill_ids or not line_ids:
            d.layers.move_top(L)
            continue

        name = L.name
        if use_groups:
            grp = d.layer_groups.new(name)
            fill_layer = d.layers.new("Fill", layer_group=grp)
            line_layer = d.layers.new("Linha", layer_group=grp)
        else:
            fill_layer = d.layers.new(name + " · Fill")
            line_layer = d.layers.new(name + " · Linha")

        _copy_strokes(sdr, fill_ids, fill_layer.frames.new(fno).drawing, fill_idx)
        _copy_strokes(sdr, line_ids, line_layer.frames.new(fno).drawing, line_idx)

        # fill embaixo, linha em cima; ambos pro topo do stack
        d.layers.move_top(fill_layer)
        d.layers.move_top(line_layer)
        d.layers.remove(L)


# ------------------------------------------------------------------ normalizar
def _bbox(d):
    mn = [1e18, 1e18, 1e18]
    mx = [-1e18, -1e18, -1e18]
    found = False
    for L in d.layers:
        for fr in L.frames:
            for s in fr.drawing.strokes:
                for p in s.points:
                    co = p.position
                    found = True
                    for a in range(3):
                        if co[a] < mn[a]:
                            mn[a] = co[a]
                        if co[a] > mx[a]:
                            mx[a] = co[a]
    if not found:
        return None
    return mn, mx


def _normalize(gp_obj, target_h, recenter):
    d = gp_obj.data
    bb = _bbox(d)
    if bb is None:
        return
    mn, mx = bb
    center = [(mn[a] + mx[a]) * 0.5 for a in range(3)]
    dims = [mx[a] - mn[a] for a in range(3)]
    biggest = max(dims)
    sc = (target_h / biggest) if (target_h > 0 and biggest > 0) else 1.0
    cx, cy, cz = (center if recenter else (0.0, 0.0, 0.0))

    def _xf(v):
        return ((v[0] - cx) * sc, (v[1] - cy) * sc, (v[2] - cz) * sc)

    for L in d.layers:
        for fr in L.frames:
            dr = fr.drawing
            for s in dr.strokes:
                for p in s.points:
                    p.position = _xf(p.position)
                    p.radius = p.radius * sc
            # handles sao posicoes absolutas -> mesma transformada, via atributo
            for nm in ('handle_left', 'handle_right'):
                a = dr.attributes.get(nm)
                if a is None:
                    continue
                for i in range(len(a.data)):
                    a.data[i].vector = _xf(a.data[i].vector)
            for tag in ('tag_positions_changed', 'tag_radii_changed'):
                if hasattr(dr, tag):
                    try:
                        getattr(dr, tag)()
                    except Exception:
                        pass


# ------------------------------------------------------------------ processo
def _newest_gp_object(before_names):
    cands = [o for o in bpy.data.objects
             if o.type == 'GREASEPENCIL' and o.name not in before_names]
    return cands[-1] if cands else None


def _process_one(context, filepath, opts, grid_index):
    before = set(o.name for o in bpy.data.objects)
    bpy.ops.wm.grease_pencil_import_svg(
        filepath=filepath, scale=opts['scale'],
        resolution=opts['resolution'], use_scene_unit=False)
    gp_obj = _newest_gp_object(before)
    if gp_obj is None:
        return None

    if opts['split']:
        _split_line_fill(gp_obj, opts['groups'])
    if opts['normalize']:
        _normalize(gp_obj, opts['target_h'], recenter=True)

    # posicionamento em grade pro lote
    spacing = (opts['target_h'] if opts['normalize'] and opts['target_h'] > 0 else 2.0) * 1.3
    gp_obj.location = (grid_index * spacing, 0.0, 0.0)
    return gp_obj


# ------------------------------------------------------------------ operador
class SVG2GP_OT_import(Operator, ImportHelper):
    bl_idname = "svg2gp.import_svg"
    bl_label = "Importar SVG → GP"
    bl_description = "Importa um ou varios SVG como Grease Pencil, com separacao linha/fill, lote e normalizacao"
    bl_options = {'REGISTER', 'UNDO'}

    filename_ext = ".svg"
    filter_glob: StringProperty(default="*.svg", options={'HIDDEN'})
    files: CollectionProperty(name="Arquivos", type=OperatorFileListElement)
    directory: StringProperty(subtype='DIR_PATH')

    # espelham o nativo
    scale: FloatProperty(name="Escala", default=10.0, min=0.001, max=1000.0)
    resolution: IntProperty(name="Resolucao", default=10, min=1, max=50)

    # extras do helper
    split_line_fill: BoolProperty(
        name="Separar linha/fill", default=True,
        description="Quebra material 'Both' e separa linha e fill em camadas (pronto pro auto-patch)")
    use_layer_groups: BoolProperty(
        name="Agrupar por camada", default=True,
        description="Poe Linha/Fill dentro de um grupo de camadas por shape/grupo do SVG")
    normalize: BoolProperty(
        name="Normalizar tamanho/posicao", default=True,
        description="Recentra na origem e escala pra altura alvo")
    target_height: FloatProperty(
        name="Altura alvo", default=2.0, min=0.0, max=1000.0,
        description="Maior dimensao vira esse valor (0 = nao escalar)")

    def execute(self, context):
        opts = {
            'scale': self.scale, 'resolution': self.resolution,
            'split': self.split_line_fill, 'groups': self.use_layer_groups,
            'normalize': self.normalize, 'target_h': self.target_height,
        }
        # lista de arquivos (multi-selecao ou unico)
        paths = []
        if self.files and self.directory:
            for f in self.files:
                if f.name:
                    paths.append(os.path.join(self.directory, f.name))
        if not paths and self.filepath:
            paths = [self.filepath]
        paths = [p for p in paths if p.lower().endswith(".svg") and os.path.isfile(p)]
        if not paths:
            self.report({'WARNING'}, "Nenhum .svg valido selecionado")
            return {'CANCELLED'}

        made = 0
        for i, p in enumerate(paths):
            try:
                obj = _process_one(context, p, opts, i)
                if obj is not None:
                    made += 1
            except Exception as e:
                self.report({'WARNING'}, f"Falha em {os.path.basename(p)}: {e}")
        self.report({'INFO'}, f"Importados {made}/{len(paths)} SVG → GP")
        return {'FINISHED'} if made else {'CANCELLED'}


# ------------------------------------------------------ export (GP -> SVG/PDF)
def _world_bbox(objs):
    mn = [1e18, 1e18, 1e18]
    mx = [-1e18, -1e18, -1e18]
    found = False
    for ob in objs:
        mw = ob.matrix_world
        for L in ob.data.layers:
            for fr in L.frames:
                for s in fr.drawing.strokes:
                    for p in s.points:
                        co = mw @ Vector(p.position)
                        found = True
                        for a in range(3):
                            if co[a] < mn[a]:
                                mn[a] = co[a]
                            if co[a] > mx[a]:
                                mx[a] = co[a]
    if not found:
        return (-1.0, -1.0, -1.0), (1.0, 1.0, 1.0)
    return mn, mx


def _make_front_ortho_camera(context, objs, margin=1.1):
    """Cria uma camera ORTOGRAFICA olhando de frente (-Y) enquadrando objs. Retorna o objeto camera."""
    mn, mx = _world_bbox(objs)
    cx = (mn[0] + mx[0]) * 0.5
    cz = (mn[2] + mx[2]) * 0.5
    w = mx[0] - mn[0]
    h = mx[2] - mn[2]
    depth = max(mx[1] - mn[1], 1.0)

    cam_data = bpy.data.cameras.new("SVG2GP_Cam")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = max(w, h, 1e-3) * margin
    cam = bpy.data.objects.new("SVG2GP_Cam", cam_data)
    context.scene.collection.objects.link(cam)
    # de frente: olhar +Y a partir de -Y; rot +90deg em X faz a camera (que olha -Z) olhar +Y
    cam.location = (cx, mn[1] - depth * 2.0 - 1.0, cz)
    cam.rotation_euler = (math.pi / 2.0, 0.0, 0.0)
    return cam


class SVG2GP_OT_export_svg(Operator, ExportHelper):
    bl_idname = "svg2gp.export_svg"
    bl_label = "Exportar GP → SVG"
    bl_description = "Exporta o Grease Pencil ativo para SVG, montando uma camera ortografica de frente automaticamente"
    bl_options = {'REGISTER'}

    filename_ext = ".svg"
    filter_glob: StringProperty(default="*.svg", options={'HIDDEN'})

    use_fill: BoolProperty(
        name="Exportar fills", default=True,
        description="Inclui os preenchimentos (nao so as linhas)")
    scope: EnumProperty(
        name="O que exportar",
        default='SELECTED',
        items=[
            ('SELECTED', "Selecionados", "Exporta o(s) Grease Pencil SELECIONADO(s)"),
            ('ACTIVE', "Ativo", "Exporta apenas o objeto ativo"),
            ('VISIBLE', "Visiveis", "Exporta todos os Grease Pencil visiveis"),
        ])
    auto_camera: BoolProperty(
        name="Camera ortografica automatica", default=True,
        description="Cria uma camera ORTHO de frente enquadrando o desenho, exporta e a remove")
    uniform_width: BoolProperty(
        name="Espessura uniforme", default=False,
        description="Forca largura de linha constante no SVG")

    @classmethod
    def poll(cls, context):
        return any(o.type == 'GREASEPENCIL' for o in context.scene.objects)

    def execute(self, context):
        scene = context.scene
        active = context.view_layer.objects.active

        # objetos no escopo escolhido (default = SELECIONADOS)
        if self.scope == 'SELECTED':
            objs = [o for o in context.selected_objects if o.type == 'GREASEPENCIL']
        elif self.scope == 'VISIBLE':
            objs = [o for o in scene.objects if o.type == 'GREASEPENCIL' and o.visible_get()]
        else:  # ACTIVE
            objs = [active] if (active and active.type == 'GREASEPENCIL') else []

        if not objs:
            self.report({'WARNING'},
                        "Nada para exportar: selecione um Grease Pencil (escopo: %s)" % self.scope)
            return {'CANCELLED'}

        # O export nativo 'ACTIVE' usa o objeto ativo; garantir que o ativo
        # seja um dos selecionados para o resultado bater com a selecao.
        if self.scope == 'SELECTED' and (active not in objs):
            context.view_layer.objects.active = objs[0]

        prev_cam = scene.camera
        temp_cam = None
        if self.auto_camera or scene.camera is None:
            temp_cam = _make_front_ortho_camera(context, objs)
            scene.camera = temp_cam

        try:
            res = bpy.ops.wm.grease_pencil_export_svg(
                filepath=self.filepath,
                use_fill=self.use_fill,
                selected_object_type=self.scope,
                frame_mode='ACTIVE',
                use_uniform_width=self.uniform_width)
        except Exception as e:
            res = {'CANCELLED'}
            self.report({'WARNING'}, f"Falha no export: {e}")
        finally:
            scene.camera = prev_cam
            if temp_cam is not None:
                cam_data = temp_cam.data
                bpy.data.objects.remove(temp_cam, do_unlink=True)
                if cam_data.users == 0:
                    bpy.data.cameras.remove(cam_data)

        if 'FINISHED' in res:
            self.report({'INFO'}, f"Exportado: {os.path.basename(self.filepath)}")
            return {'FINISHED'}
        return {'CANCELLED'}


# ------------------------------------------------------------------ UI
class SVG2GP_PT_panel(Panel):
    bl_label = "SVG → Grease Pencil"
    bl_idname = "SVG2GP_PT_panel"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "SVG→GP"

    def draw(self, context):
        col = self.layout.column()
        col.operator("svg2gp.import_svg", icon='IMPORT', text="Importar SVG → GP…")
        col.label(text="Multi-selecao = lote", icon='INFO')
        col.separator()
        col.operator("svg2gp.export_svg", icon='EXPORT', text="Exportar GP → SVG…")
        col.label(text="Camera ortografica automatica", icon='INFO')


def _menu_import(self, context):
    self.layout.operator("svg2gp.import_svg", text="SVG como Grease Pencil (helper)")


def _menu_export(self, context):
    self.layout.operator("svg2gp.export_svg", text="Grease Pencil como SVG (helper)")


classes = (SVG2GP_OT_import, SVG2GP_OT_export_svg, SVG2GP_PT_panel)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.TOPBAR_MT_file_import.append(_menu_import)
    bpy.types.TOPBAR_MT_file_export.append(_menu_export)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(_menu_export)
    bpy.types.TOPBAR_MT_file_import.remove(_menu_import)
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
