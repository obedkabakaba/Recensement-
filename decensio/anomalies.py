"""Repérage des saisies suspectes.

Trois niveaux de contrôle :
- **ménage** : GPS absent ou imprécis, hors de la zone assignée, taille aberrante, heure de saisie…
- **personne** : âge invraisemblable, chef de ménage trop jeune, écart d'âge parent-enfant…
- **agent** : rythme trop rapide, points GPS empilés, âges arrondis, rapport hommes/femmes anormal.

Une anomalie n'est pas une preuve de fraude : c'est un signal à vérifier sur le terrain.
Les anomalies justifiées par un superviseur gardent ce statut d'un calcul à l'autre.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, selectinload

from .config import Parametres
from .geo import distance_m, valider_coordonnees
from .models import Anomalie, Menage, Zone

LIBELLES = {
    "gps_absent": "Coordonnées GPS absentes ou invalides",
    "gps_imprecis": "GPS imprécis",
    "hors_zones": "Point GPS en dehors de toutes les zones connues",
    "hors_zone_assignee": "Ménage enregistré hors de la zone assignée à l'agent",
    "menage_vide": "Ménage sans aucun membre",
    "taille_aberrante": "Ménage anormalement grand",
    "taille_incoherente": "Nombre de membres différent de la taille déclarée",
    "sans_chef": "Aucun chef de ménage",
    "plusieurs_chefs": "Plusieurs chefs de ménage",
    "hors_horaires": "Saisie en dehors des heures de travail",
    "date_future": "Date de collecte dans le futur",
    "age_invraisemblable": "Âge invraisemblable",
    "chef_trop_jeune": "Chef de ménage très jeune",
    "ecart_age_parent_enfant": "Écart d'âge chef-enfant trop faible",
    "nom_manquant": "Nom manquant",
    "rythme_trop_rapide": "Ménage enregistré trop vite après le précédent",
    "trop_de_menages_par_jour": "Nombre de ménages par jour anormalement élevé",
    "empilement_gps": "Plusieurs ménages enregistrés au même point GPS",
    "ages_arrondis": "Attraction des âges ronds (âges probablement estimés)",
    "rapport_masculinite": "Rapport hommes/femmes anormal",
    "menages_trop_petits": "Taille moyenne des ménages anormalement basse",
}


@dataclass
class Signal:
    type: str
    gravite: str
    cible: str
    message: str
    menage_id: int | None = None
    personne_id: int | None = None
    agent_id: str | None = None
    zone_id: int | None = None
    valeur: float | None = None

    @property
    def cle(self) -> tuple:
        return (self.type, self.menage_id, self.personne_id, self.agent_id if self.cible == "agent" else None)


def _utc(dt: datetime) -> datetime:
    """Les bases SQLite renvoient des dates sans fuseau : ce sont des heures UTC."""
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def _heure_locale(dt: datetime, decalage: int) -> datetime:
    return _utc(dt).astimezone(timezone(timedelta(hours=decalage)))


def _ancetres(code: str | None, parents: dict[str, str | None]) -> set[str]:
    vus: set[str] = set()
    while code and code not in vus:
        vus.add(code)
        code = parents.get(code)
    return vus


def controler_menages(menages: list[Menage], zones: dict[int, Zone], params: Parametres) -> list[Signal]:
    signaux: list[Signal] = []
    parents = {z.code: z.code_parent for z in zones.values()}
    maintenant = datetime.now(timezone.utc)
    for m in menages:
        def sig(type_: str, gravite: str, detail: str = "", valeur: float | None = None, personne_id: int | None = None, cible: str = "menage") -> None:
            message = LIBELLES[type_] + (f" : {detail}" if detail else "")
            signaux.append(Signal(type_, gravite, cible, message, m.id, personne_id, m.agent_id, m.zone_id, valeur))

        # --- Localisation
        if not valider_coordonnees(m.lat, m.lon):
            sig("gps_absent", "haute")
        else:
            if m.precision_gps_m is not None and m.precision_gps_m > params.precision_gps_max_m:
                sig("gps_imprecis", "basse", f"précision {m.precision_gps_m:.0f} m", m.precision_gps_m)
            if zones and m.zone_id is None:
                sig("hors_zones", "moyenne")
            elif m.zone_assignee_code and m.zone_id is not None:
                zone_gps = zones.get(m.zone_id)
                if zone_gps and m.zone_assignee_code not in _ancetres(zone_gps.code, parents):
                    sig("hors_zone_assignee", "moyenne", f"assignée {m.zone_assignee_code}, GPS dans {zone_gps.code} ({zone_gps.nom})")

        # --- Composition
        membres = list(m.personnes)
        if not membres:
            sig("menage_vide", "moyenne")
        else:
            if len(membres) > params.taille_menage_max:
                sig("taille_aberrante", "moyenne", f"{len(membres)} membres", len(membres))
            if m.taille_declaree is not None and m.taille_declaree != len(membres):
                sig("taille_incoherente", "basse", f"{len(membres)} saisis pour {m.taille_declaree} déclarés", len(membres) - m.taille_declaree)
            liens = [p.lien for p in membres if p.lien]
            if liens:
                chefs = [p for p in membres if p.lien == "chef"]
                if not chefs:
                    sig("sans_chef", "basse")
                elif len(chefs) > 1:
                    sig("plusieurs_chefs", "moyenne", f"{len(chefs)} chefs", len(chefs))
                chef = chefs[0] if chefs else None
            else:
                chef = None

            for p in membres:
                if p.age is not None and (p.age < 0 or p.age > 110):
                    sig("age_invraisemblable", "moyenne", f"{p.age} ans", p.age, p.id, "personne")
                if not p.cles_phonetiques:
                    sig("nom_manquant", "moyenne", f"membre n° {p.rang}", None, p.id, "personne")
            if chef is not None and chef.age is not None:
                if 0 <= chef.age < 12:
                    sig("chef_trop_jeune", "moyenne", f"{chef.age} ans", chef.age, chef.id, "personne")
                for p in membres:
                    if p.lien == "enfant" and p.age is not None and chef.age - p.age < 12:
                        sig("ecart_age_parent_enfant", "basse", f"chef {chef.age} ans, enfant {p.age} ans", chef.age - p.age, p.id, "personne")

        # --- Heure de collecte
        if m.collecte_le is not None:
            collecte = _utc(m.collecte_le)
            if collecte > maintenant + timedelta(days=1):
                sig("date_future", "haute", collecte.date().isoformat())
            heure = _heure_locale(collecte, params.decalage_horaire).hour
            if heure < params.heure_debut_travail or heure >= params.heure_fin_travail:
                sig("hors_horaires", "basse", f"{heure} h", heure)
    return signaux


def indice_whipple(ages: list[int]) -> float | None:
    """Indice de Whipple (23 à 62 ans) : 100 = pas d'attraction ; 500 = tous les âges finissent par 0 ou 5."""
    plage = [a for a in ages if 23 <= a <= 62]
    if not plage:
        return None
    ronds = sum(1 for a in plage if a % 5 == 0)
    return 100 * ronds / (len(plage) / 5)


def controler_agents(menages: list[Menage], params: Parametres) -> list[Signal]:
    signaux: list[Signal] = []
    par_agent: dict[str, list[Menage]] = defaultdict(list)
    for m in menages:
        if m.agent_id:
            par_agent[m.agent_id].append(m)

    for agent, liste in par_agent.items():
        # --- Rythme de travail
        dates = sorted((m for m in liste if m.collecte_le), key=lambda m: _utc(m.collecte_le))  # type: ignore[arg-type]
        for prec, suiv in zip(dates, dates[1:]):
            ecart = (_utc(suiv.collecte_le) - _utc(prec.collecte_le)).total_seconds()  # type: ignore[arg-type]
            if 0 <= ecart < params.duree_min_entre_menages_s and len(suiv.personnes) >= 2:
                signaux.append(Signal(
                    "rythme_trop_rapide", "moyenne", "menage",
                    f"{LIBELLES['rythme_trop_rapide']} : {ecart:.0f} s pour {len(suiv.personnes)} personnes",
                    suiv.id, None, agent, suiv.zone_id, ecart,
                ))
        par_jour: dict[str, int] = defaultdict(int)
        for m in dates:
            par_jour[_heure_locale(m.collecte_le, params.decalage_horaire).date().isoformat()] += 1  # type: ignore[arg-type]
        for jour, nb in par_jour.items():
            if nb > params.menages_max_par_jour:
                signaux.append(Signal(
                    "trop_de_menages_par_jour", "moyenne", "agent",
                    f"{LIBELLES['trop_de_menages_par_jour']} : {nb} ménages le {jour}",
                    None, None, agent, None, nb,
                ))

        # --- Points GPS empilés (saisie depuis un seul endroit ?)
        points = [m for m in liste if valider_coordonnees(m.lat, m.lon)]
        pas = params.rayon_empilement_m / 111_000  # taille d'une case de la grille, en degrés
        cases: dict[tuple[int, int], list[Menage]] = defaultdict(list)
        for m in points:
            cases[(int(m.lat // pas), int(m.lon // pas))].append(m)  # type: ignore[operator]
        deja: set[int] = set()
        for m in points:
            if m.id in deja:
                continue
            ci, cj = int(m.lat // pas), int(m.lon // pas)  # type: ignore[operator]
            voisins = [
                n for di in (-1, 0, 1) for dj in (-1, 0, 1) for n in cases.get((ci + di, cj + dj), [])
                if n.id != m.id and distance_m(m.lat, m.lon, n.lat, n.lon) <= params.rayon_empilement_m  # type: ignore[arg-type]
            ]
            if len(voisins) + 1 >= params.empilement_min:
                groupe = [m, *voisins]
                deja.update(x.id for x in groupe)
                signaux.append(Signal(
                    "empilement_gps", "haute", "agent",
                    f"{LIBELLES['empilement_gps']} : {len(groupe)} ménages dans un rayon de {params.rayon_empilement_m:.0f} m "
                    "(à vérifier : immeuble ou saisie à distance)",
                    m.id, None, agent, m.zone_id, len(groupe),
                ))

        # --- Indicateurs démographiques de l'agent
        personnes = [p for m in liste for p in m.personnes]
        ages = [p.age for p in personnes if p.age is not None]
        w = indice_whipple(ages)
        if w is not None and len([a for a in ages if 23 <= a <= 62]) >= 50 and w > 175:
            signaux.append(Signal("ages_arrondis", "moyenne", "agent", f"{LIBELLES['ages_arrondis']} : indice de Whipple {w:.0f}", None, None, agent, None, round(w, 1)))
        hommes = sum(1 for p in personnes if p.sexe == "M")
        femmes = sum(1 for p in personnes if p.sexe == "F")
        if hommes + femmes >= 100 and femmes > 0:
            rapport = 100 * hommes / femmes
            if rapport < 70 or rapport > 140:
                signaux.append(Signal("rapport_masculinite", "basse", "agent", f"{LIBELLES['rapport_masculinite']} : {rapport:.0f} hommes pour 100 femmes", None, None, agent, None, round(rapport, 1)))
        if len(liste) >= 20:
            moyenne = len(personnes) / len(liste)
            if moyenne < 2.5:
                signaux.append(Signal("menages_trop_petits", "basse", "agent", f"{LIBELLES['menages_trop_petits']} : {moyenne:.1f} personnes par ménage (membres oubliés ?)", None, None, agent, None, round(moyenne, 2)))
    return signaux


def detecter_anomalies(s: Session, params: Parametres) -> dict:
    """Recalcule toutes les anomalies ; conserve les décisions (justifiée / corrigée)."""
    menages = list(s.scalars(select(Menage).options(selectinload(Menage.personnes))).all())
    zones = {z.id: z for z in s.scalars(select(Zone)).all()}
    signaux = controler_menages(menages, zones, params) + controler_agents(menages, params)

    decisions: dict[tuple, str] = {}
    for a in s.scalars(select(Anomalie).where(Anomalie.statut != "ouverte")).all():
        decisions[(a.type, a.menage_id, a.personne_id, a.agent_id if a.cible == "agent" else None)] = a.statut
    s.execute(delete(Anomalie))
    for sig in signaux:
        s.add(Anomalie(
            type=sig.type, gravite=sig.gravite, cible=sig.cible, menage_id=sig.menage_id,
            personne_id=sig.personne_id, agent_id=sig.agent_id, zone_id=sig.zone_id,
            message=sig.message, valeur=sig.valeur, statut=decisions.get(sig.cle, "ouverte"),
        ))
    s.flush()
    compte: dict[str, int] = defaultdict(int)
    for sig in signaux:
        compte[sig.gravite] += 1
    return {"total": len(signaux), **compte}
