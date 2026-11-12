"""Couverture : population déjà enregistrée comparée à la population attendue, zone par zone.

Statuts :
- **vert**          : couverture atteinte (≥ seuil vert, 90 % par défaut) ;
- **orange**        : en cours (entre le seuil orange et le seuil vert) ;
- **rouge**         : sous-couverture (< seuil orange, 70 % par défaut) ;
- **surcouverture** : plus de personnes que prévu (doublons non repérés ou estimation trop basse) ;
- **sans_estimation** / **indeterminee** : pas d'estimation, ou zone trop peu peuplée pour conclure.

Chaque personne n'est comptée qu'une fois : les fiches en double (même groupe) ne comptent pas.
Les zones parentes (commune, zone de santé) cumulent leurs zones filles.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import case, delete, func, or_, select
from sqlalchemy.orm import Session

from .config import Parametres
from .models import CouvertureZone, EstimationPopulation, Menage, Personne, Zone

# Ordre de préférence des sources d'estimation (la première disponible est retenue).
PRIORITE_SOURCES = ["RGPH", "INS", "GRID3", "WORLDPOP"]


@dataclass
class Comptes:
    menages: int = 0
    personnes: int = 0
    uniques: int = 0

    def __iadd__(self, autre: "Comptes") -> "Comptes":
        self.menages += autre.menages
        self.personnes += autre.personnes
        self.uniques += autre.uniques
        return self


def statut_couverture(taux: float | None, population: float | None, params: Parametres) -> str:
    if population is None:
        return "sans_estimation"
    if population < params.population_minimale:
        return "indeterminee"
    assert taux is not None
    if taux >= params.seuil_surcouverture:
        return "surcouverture"
    if taux >= params.seuil_vert:
        return "vert"
    if taux >= params.seuil_orange:
        return "orange"
    return "rouge"


def _rang_source(source: str) -> int:
    s = source.upper()
    for i, prefixe in enumerate(PRIORITE_SOURCES):
        if s.startswith(prefixe):
            return i
    return len(PRIORITE_SOURCES)


def calculer_couverture(s: Session, params: Parametres) -> dict:
    zones = {z.id: z for z in s.scalars(select(Zone)).all()}
    par_code = {z.code: z.id for z in zones.values()}
    enfants: dict[int, list[int]] = defaultdict(list)
    for z in zones.values():
        if z.code_parent and z.code_parent in par_code:
            enfants[par_code[z.code_parent]].append(z.id)

    # Comptes directs par zone (zone la plus fine contenant le point GPS).
    directs: dict[int, Comptes] = defaultdict(Comptes)
    for zone_id, nb in s.execute(select(Menage.zone_id, func.count()).where(Menage.zone_id.is_not(None)).group_by(Menage.zone_id)):
        directs[zone_id].menages = nb
    requete_personnes = (
        select(
            Menage.zone_id,
            func.count(Personne.id),
            func.sum(case((or_(Personne.groupe_id.is_(None), Personne.groupe_id == Personne.id), 1), else_=0)),
        )
        .join(Menage, Menage.id == Personne.menage_id)
        .where(Menage.zone_id.is_not(None))
        .group_by(Menage.zone_id)
    )
    for zone_id, nb, uniques in s.execute(requete_personnes):
        directs[zone_id].personnes = nb
        directs[zone_id].uniques = int(uniques or 0)

    # Estimations : meilleure source disponible par zone.
    estimations: dict[int, EstimationPopulation] = {}
    for e in s.scalars(select(EstimationPopulation)).all():
        actuelle = estimations.get(e.zone_id)
        if actuelle is None or _rang_source(e.source) < _rang_source(actuelle.source):
            estimations[e.zone_id] = e

    cumul: dict[int, Comptes] = {}
    pop_cumul: dict[int, tuple[float | None, str | None]] = {}

    def cumuler(zid: int, pile: frozenset = frozenset()) -> Comptes:
        if zid in cumul:
            return cumul[zid]
        c = Comptes()
        c += directs.get(zid, Comptes())
        for e in enfants.get(zid, []):
            if e not in pile:
                c += cumuler(e, pile | {zid})
        cumul[zid] = c
        return c

    def population(zid: int, pile: frozenset = frozenset()) -> tuple[float | None, str | None]:
        if zid in pop_cumul:
            return pop_cumul[zid]
        if zid in estimations:
            resultat = (estimations[zid].population, estimations[zid].source)
        else:
            valeurs = [population(e, pile | {zid}) for e in enfants.get(zid, []) if e not in pile]
            connues = [v for v in valeurs if v[0] is not None]
            resultat = (sum(v[0] for v in connues), connues[0][1] + " (somme)") if connues else (None, None)  # type: ignore[misc]
        pop_cumul[zid] = resultat
        return resultat

    s.execute(delete(CouvertureZone))
    resume: dict[str, int] = defaultdict(int)
    for zid in zones:
        c = cumuler(zid)
        pop, source = population(zid)
        taux = (c.uniques / pop) if pop else (None if pop is None else 0.0)
        statut = statut_couverture(taux, pop, params)
        resume[statut] += 1
        s.add(CouvertureZone(
            zone_id=zid, source_estimation=source, population_estimee=pop, menages=c.menages,
            personnes_enregistrees=c.personnes, personnes_uniques=c.uniques,
            taux=round(taux, 4) if taux is not None else None, statut=statut,
        ))
    s.flush()
    return {"zones": len(zones), **resume}
