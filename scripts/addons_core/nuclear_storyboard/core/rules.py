"""Validacao das regras de negocio do PRD.

Toda regra vira um `Issue` com nivel, para a UI mostrar contador e o export
decidir se segue ou trava. Nada aqui altera o projeto.

  RN01  todo take precisa de >= 2 desenhos.
  RN02  layer de BG so em escala de cinza (luminosidade 0-100%).
  RN03  personagem do board precisa estar ligado a um rig antes do export.
  RN04  substituicao de prop propaga para todos os takes.
  RN05  entre desenhos so existe hold (validado no timing, nao aqui).
  RN06  burning obrigatorio no export.

Alem das do PRD, ha uma regra nossa: NSB01 avisa quando dois takes compartilham
o mesmo caminho EP/CENA/TAKE, o que tornaria ambigua a origem das mensagens.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional

from .model import Library, Project, Take, normalize_hex
from .storage import ProjectPaths

ERROR = "error"
WARNING = "warning"
INFO = "info"

#: RN01. O PRD pedia 2, mas plano estático de um desenho só é storyboard normal
#: — o animatic real do Ep03 tem dois — e o mínimo de 2 barrava o export do
#: material do estúdio. Take VAZIO continua erro: aí não há o que exportar.
#: Decisão do usuário em 2026-07-31.
MIN_DRAWINGS = 1


@dataclass
class Issue:
    level: str
    code: str
    message: str
    where: str = ""

    def __str__(self) -> str:
        prefix = {ERROR: "ERRO", WARNING: "AVISO", INFO: "INFO"}[self.level]
        return f"[{prefix}] {self.where}: {self.message}" if self.where else f"[{prefix}] {self.message}"


def is_grayscale(rgb, tolerance: float = 0.02) -> bool:
    """RN02: R==G==B dentro de uma tolerancia (float 0..1)."""
    r, g, b = rgb[:3]
    return max(r, g, b) - min(r, g, b) <= tolerance


def validate_take(take: Take, library: Library, paths: Optional[ProjectPaths] = None,
                  where: str = "") -> List[Issue]:
    issues: List[Issue] = []
    where = where or take.code or take.name or take.id

    # RN01
    if len(take.drawings) < MIN_DRAWINGS:
        issues.append(Issue(ERROR, "RN01", "take sem nenhum desenho", where))

    if not take.audios:
        issues.append(Issue(WARNING, "RF-A03",
                            "take sem audio: a duracao cai no padrao de take mudo", where))

    for audio in take.audios:
        if audio.start < 0:
            issues.append(Issue(ERROR, "RF-A02",
                                f"audio '{audio.name}' comeca antes do zero", where))
        if audio.duration <= 0:
            issues.append(Issue(ERROR, "RF-A01",
                                f"audio '{audio.name}' tem duracao zero (arquivo corrompido?)", where))
        if paths and audio.file and not paths.abs(audio.file).is_file():
            issues.append(Issue(ERROR, "RF-A01",
                                f"arquivo de audio sumiu: {audio.file}", where))

    for i, drawing in enumerate(take.drawings):
        if drawing.exposure is not None and drawing.exposure <= 0:
            issues.append(Issue(ERROR, "RF-T02",
                                f"desenho {i + 1} com exposicao <= 0", where))

    # RN03 — personagem sem rig vinculado
    for cid in take.character_ids:
        char = next((c for c in library.characters if c.id == cid), None)
        if char is None:
            issues.append(Issue(ERROR, "RN03",
                                f"take aponta para personagem inexistente na biblioteca ({cid})", where))
        elif not char.is_linked:
            issues.append(Issue(WARNING, "RN03",
                                f"personagem '{char.name}' ({char.hex_color}) nao tem rig vinculado", where))

    # RF-D05 — prop provisorio
    for pid in take.prop_ids:
        prop = next((p for p in library.props if p.id == pid), None)
        if prop is None:
            issues.append(Issue(ERROR, "RF-B01",
                                f"take aponta para prop inexistente na biblioteca ({pid})", where))
        elif prop.temporary:
            final = library.resolve_prop(pid)
            if final is not None and final.id != pid:
                issues.append(Issue(INFO, "RN04",
                                    f"prop '{prop.name}' foi substituido por '{final.name}'", where))
            else:
                issues.append(Issue(INFO, "RF-D05",
                                    f"prop '{prop.name}' ainda e temporario", where))

    return issues


def validate_library(library: Library) -> List[Issue]:
    issues: List[Issue] = []
    seen = {}
    for char in library.characters:
        try:
            key = normalize_hex(char.hex_color)
        except ValueError as exc:
            issues.append(Issue(ERROR, "RF-D04", str(exc), char.name or char.id))
            continue
        if key in seen:
            issues.append(Issue(ERROR, "RF-B01",
                                f"cor {key} ja pertence a '{seen[key]}': a cor hex e chave unica no projeto",
                                char.name or char.id))
        else:
            seen[key] = char.name or char.id
    return issues


def validate_project(project: Project, library: Library,
                     paths: Optional[ProjectPaths] = None,
                     take_ids: Optional[Iterable[str]] = None) -> List[Issue]:
    """Valida o projeto inteiro ou so um recorte de takes.

    O recorte existe por causa do RF-13: assistir a uma cena nao pode travar
    porque uma OUTRA cena ainda esta pela metade.
    """
    wanted = set(take_ids) if take_ids is not None else None
    issues = validate_library(library)

    if project.settings.fps <= 0:
        issues.append(Issue(ERROR, "RNF", "fps precisa ser positivo", "settings"))

    if project.burnin.enabled and project.burnin.image:
        if paths and not paths.abs(project.burnin.image).is_file():
            issues.append(Issue(WARNING, "RN06",
                                f"imagem do burning nao encontrada: {project.burnin.image}", "burning"))

    # NSB01 — dois takes com o mesmo caminho EP/CENA/TAKE deixam toda mensagem
    # ambigua: o `where` de um erro passa a apontar para dois takes diferentes.
    # Nao e regra do PRD, e higiene nossa; por isso e AVISO, nao erro.
    seen_where = {}
    for ep, sc, tk in project.iter_takes():
        key = f"{ep.code}/{sc.code}/{tk.code}"
        seen_where[key] = seen_where.get(key, 0) + 1

    empty = True
    reported_dup = set()
    for ep, sc, tk in project.iter_takes():
        if wanted is not None and tk.id not in wanted:
            continue
        empty = False
        where = f"{ep.code}/{sc.code}/{tk.code}"
        if seen_where[where] > 1 and where not in reported_dup:
            reported_dup.add(where)
            issues.append(Issue(WARNING, "NSB01",
                                f"{seen_where[where]} takes com o mesmo codigo: "
                                "renomeie para as mensagens nao ficarem ambiguas",
                                where))
        issues.extend(validate_take(tk, library, paths, where))

    if empty:
        issues.append(Issue(ERROR, "RF-T01", "projeto nao tem nenhum take", "projeto"))

    return issues


def blocks_export(issues: List[Issue], strict_hex_link: bool = False) -> List[Issue]:
    """Filtra o que impede o export.

    Erros sempre travam. RN03 (personagem sem rig) so trava quando o projeto
    esta em modo estrito — o PRD nao decide entre bloquear e avisar, entao a
    escolha e do diretor de animacao, por projeto.
    """
    blocking = [i for i in issues if i.level == ERROR]
    if strict_hex_link:
        blocking += [i for i in issues if i.level == WARNING and i.code == "RN03"]
    return blocking
