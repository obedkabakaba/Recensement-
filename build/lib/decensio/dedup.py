"""Détection des doublons : la même personne enregistrée plusieurs fois.

Méthode :
1. **Regroupement** : on ne compare que les fiches qui partagent une clé phonétique de nom
   et le même sexe (ou le même NIN). Cela évite de comparer tout le monde avec tout le monde.
2. **Score** de 0 à 1 qui combine : nom (50 %), naissance (30 %), lieu (15 %), lien de parenté (5 %).
   Un sexe différent ou deux NIN différents font fortement baisser le score ;
   un même NIN donne un score de 1.
3. **Ménages en double** : si plusieurs membres de deux ménages se correspondent,
   les paires sont renforcées (ménage visité deux fois).
4. **Groupes** : les fiches reliées par des doublons probables ou confirmés forment
   une seule personne, comptée une fois dans la couverture.

Les décisions des vérificateurs (confirmé / rejeté) sont conservées d'un calcul à l'autre.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date

from rapidfuzz.distance import JaroWinkler
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .config import Parametres
from .geo import distance_m, valider_coordonnees
from .models import CleNom, Menage, PaireDoublon, Personne

POIDS = {"nom": 0.50, "naissance": 0.30, "lieu": 0.15, "lien": 0.05}
TAILLE_MAX_BLOC = 5000
ECART_ANNEES_MAX = 2


@dataclass
class Fiche:
    id: int
    menage_id: int
    cles: list[str]
    jetons: set[str]
    sexe: str | None
    annee: int | None
    date_naissance: date | None
    nin: str | None
    lien: str | None
    lat: float | None
    lon: float | None
    zone_id: int | None


@dataclass
class ResultatPaire:
    score: float
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------- chargement


def _requete_fiches():
    return select(
        Personne.id,
        Personne.menage_id,
        Personne.cles_phonetiques,
        Personne.jetons_nom,
        Personne.sexe,
        Personne.annee_naissance,
        Personne.date_naissance,
        Personne.nin_empreinte,
        Personne.lien,
        Menage.lat,
        Menage.lon,
        Menage.zone_id,
    ).join(Menage, Menage.id == Personne.menage_id)


def _fiche(ligne) -> Fiche:
    return Fiche(
        id=ligne[0],
        menage_id=ligne[1],
        cles=(ligne[2] or "").split(),
        jetons=set((ligne[3] or "").split()),
        sexe=ligne[4],
        annee=ligne[5],
        date_naissance=ligne[6],
        nin=ligne[7],
        lien=ligne[8],
        lat=ligne[9],
        lon=ligne[10],
        zone_id=ligne[11],
    )


def charger_fiches(s: Session, ids: list[int] | None = None) -> list[Fiche]:
    req = _requete_fiches()
    if ids is not None:
        if not ids:
            return []
        req = req.where(Personne.id.in_(ids))
    return [_fiche(l) for l in s.execute(req).all()]


# ---------------------------------------------------------------- score


def similarite_noms(a: Fiche, b: Fiche) -> float:
    if not a.cles or not b.cles:
        return 0.0
    courte, longue = (a.cles, b.cles) if len(a.cles) <= len(b.cles) else (b.cles, a.cles)
    restantes = list(longue)
    meilleures: list[float] = []
    for cle in courte:
        meilleure, idx = 0.0, -1
        for i, autre in enumerate(restantes):
            sim = JaroWinkler.similarity(cle, autre)
            if sim > meilleure:
                meilleure, idx = sim, i
        meilleures.append(meilleure)
        if idx >= 0:
            restantes.pop(idx)
    moyenne = sum(meilleures) / len(meilleures)
    # Un élément du nom qui ne correspond à rien (autre prénom) : ce sont sans doute deux personnes.
    if min(meilleures) < 0.85:
        moyenne *= 0.6
    # Un élément de nom omis (souvent le postnom) coûte un peu ; un seul élément commun ne suffit pas.
    if len(courte) == 1 and len(longue) > 1:
        moyenne *= 0.8
    elif len(courte) < len(longue):
        moyenne *= 0.9
    exacts = len(a.jetons & b.jetons) / max(1, min(len(a.jetons), len(b.jetons))) if a.jetons and b.jetons else 0.0
    return 0.8 * moyenne + 0.2 * exacts


def similarite_naissance(a: Fiche, b: Fiche) -> float:
    if a.date_naissance and b.date_naissance:
        da, db = a.date_naissance, b.date_naissance
        if da == db:
            return 1.0
        if da.year == db.year and da.month == db.day and da.day == db.month:
            return 0.9  # jour et mois inversés
        if da.year == db.year:
            return 0.7
        ecart = abs(da.year - db.year)
        return 0.5 if ecart == 1 else 0.25 if ecart == 2 else 0.0
    if a.annee is not None and b.annee is not None:
        # Au moins une des deux dates vient d'un âge déclaré : précision d'environ un an.
        ecart = abs(a.annee - b.annee)
        return {0: 0.8, 1: 0.6, 2: 0.35}.get(ecart, 0.0)
    return 0.5  # information manquante : neutre


def similarite_lieu(a: Fiche, b: Fiche) -> tuple[float, float | None]:
    if valider_coordonnees(a.lat, a.lon) and valider_coordonnees(b.lat, b.lon):
        d = distance_m(a.lat, a.lon, b.lat, b.lon)  # type: ignore[arg-type]
        if d < 50:
            return 1.0, d
        if d < 250:
            return 0.8, d
        if d < 1000:
            return 0.5, d
        if a.zone_id is not None and a.zone_id == b.zone_id:
            return 0.4, d
        if d < 5000:
            return 0.2, d
        return 0.0, d
    if a.zone_id is not None and a.zone_id == b.zone_id:
        return 0.4, None
    return 0.3, None


def similarite_lien(a: Fiche, b: Fiche) -> float:
    if not a.lien or not b.lien:
        return 0.5
    return 1.0 if a.lien == b.lien else 0.0


def score_paire(a: Fiche, b: Fiche, frequence_nom: int = 1) -> ResultatPaire:
    """Score de ressemblance entre deux fiches.

    `frequence_nom` : nombre de fiches qui portent exactement le même nom. Pour un nom très
    répandu, une même année de naissance ne suffit pas à conclure : il faut la date complète
    ou un domicile proche.
    """
    if a.nin and b.nin and a.nin == b.nin:
        return ResultatPaire(1.0, {"nin": "identique"})

    nom = similarite_noms(a, b)
    naissance = similarite_naissance(a, b)
    lieu, distance = similarite_lieu(a, b)
    lien = similarite_lien(a, b)
    score = POIDS["nom"] * nom + POIDS["naissance"] * naissance + POIDS["lieu"] * lieu + POIDS["lien"] * lien

    details: dict = {
        "nom": round(nom, 3),
        "naissance": round(naissance, 3),
        "lieu": round(lieu, 3),
        "lien": round(lien, 3),
    }
    if distance is not None:
        details["distance_m"] = round(distance)
    if a.sexe and b.sexe and a.sexe != b.sexe:
        score *= 0.3
        details["sexe"] = "différent"
    if a.nin and b.nin and a.nin != b.nin:
        score *= 0.4
        details["nin"] = "différent"
    if a.menage_id == b.menage_id:
        # Dans un même ménage, deux fiches très proches sont souvent une double saisie,
        # mais il peut aussi s'agir de jumeaux : on exige une date de naissance concordante.
        details["meme_menage"] = True
        if naissance < 0.7:
            score *= 0.5
        elif naissance < 0.9:
            score = min(score, 0.80)
    if nom < 0.75:
        # Sans ressemblance forte des noms, les autres critères ne suffisent pas.
        score = min(score, 0.5)
    if frequence_nom > 3 and naissance < 1.0 and lieu < 0.8:
        # Homonymes probables : on demande une vérification plutôt que de conclure.
        score = min(score, 0.80)
        details["nom_frequent"] = frequence_nom
    if naissance < 0.6:
        score = min(score, 0.80)
    return ResultatPaire(round(min(score, 1.0), 4), details)


# ---------------------------------------------------------------- candidats


def _paires_du_bloc(bloc: list[Fiche]) -> set[tuple[int, int]]:
    paires: set[tuple[int, int]] = set()
    avec_annee = sorted((f for f in bloc if f.annee is not None), key=lambda f: f.annee)  # type: ignore[arg-type]
    sans_annee = [f for f in bloc if f.annee is None]
    # Fenêtre glissante sur l'année de naissance.
    for i, f in enumerate(avec_annee):
        j = i + 1
        while j < len(avec_annee) and avec_annee[j].annee - f.annee <= ECART_ANNEES_MAX:  # type: ignore[operator]
            g = avec_annee[j]
            paires.add((min(f.id, g.id), max(f.id, g.id)))
            j += 1
    if len(sans_annee) * len(bloc) <= TAILLE_MAX_BLOC * 50:
        for f in sans_annee:
            for g in bloc:
                if f.id != g.id:
                    paires.add((min(f.id, g.id), max(f.id, g.id)))
    return paires


def prefixes(f: Fiche) -> list[str]:
    """Début (4 lettres) de chaque clé phonétique : tolère les fautes de frappe en fin de nom."""
    return sorted({c[:4] for c in f.cles if len(c) >= 3})


def _decouper(bloc: list[Fiche]) -> list[list[Fiche]]:
    if len(bloc) <= TAILLE_MAX_BLOC:
        return [bloc]
    # Combinaison de noms très courante : on découpe par zone pour garder un calcul raisonnable.
    par_zone: dict[int | None, list[Fiche]] = defaultdict(list)
    for f in bloc:
        par_zone[f.zone_id].append(f)
    return list(par_zone.values())


def generer_candidats(fiches: list[Fiche]) -> set[tuple[int, int]]:
    """Paires de fiches à comparer.

    Deux fiches sont comparées si elles ont le même sexe et partagent **deux** éléments de nom
    (ex. nom + prénom), ou le même NIN. Les fiches qui n'ont qu'un seul élément de nom sont
    comparées à toutes celles qui partagent cet élément.
    """
    par_paire: dict[tuple, list[Fiche]] = defaultdict(list)
    seuls: dict[tuple, list[Fiche]] = defaultdict(list)
    tous: dict[tuple, list[Fiche]] = defaultdict(list)
    par_nin: dict[str, list[Fiche]] = defaultdict(list)
    for f in fiches:
        if f.nin:
            par_nin[f.nin].append(f)
        prefs = prefixes(f)
        # Sexe inconnu : la fiche est comparée aux hommes comme aux femmes.
        for sexe in ([f.sexe] if f.sexe else ["M", "F"]):
            if len(prefs) == 1:
                seuls[(sexe, prefs[0])].append(f)
            for i, p1 in enumerate(prefs):
                tous[(sexe, p1)].append(f)
                for p2 in prefs[i + 1:]:
                    par_paire[(sexe, p1, p2)].append(f)

    paires: set[tuple[int, int]] = set()
    for groupe in par_nin.values():
        for i, f in enumerate(groupe):
            for g in groupe[i + 1:]:
                paires.add((min(f.id, g.id), max(f.id, g.id)))
    for bloc in par_paire.values():
        if len(bloc) > 1:
            for sous_bloc in _decouper(bloc):
                paires |= _paires_du_bloc(sous_bloc)
    for cle, isoles in seuls.items():
        ids_isoles = {f.id for f in isoles}
        for sous_bloc in _decouper(tous[cle]):
            for a_id, b_id in _paires_du_bloc(sous_bloc):
                if a_id in ids_isoles or b_id in ids_isoles:
                    paires.add((a_id, b_id))
    return paires


# ---------------------------------------------------------------- calcul et enregistrement


def _niveau(score: float, params: Parametres) -> str | None:
    if score >= params.seuil_doublon_probable:
        return "probable"
    if score >= params.seuil_doublon_a_verifier:
        return "a_verifier"
    return None


def evaluer(fiches: dict[int, Fiche], paires: set[tuple[int, int]], params: Parametres) -> dict[tuple[int, int], ResultatPaire]:
    retenues: dict[tuple[int, int], ResultatPaire] = {}
    frequences: dict[tuple[str, ...], int] = defaultdict(int)
    for f in fiches.values():
        frequences[tuple(f.cles)] += 1
    for a_id, b_id in paires:
        a, b = fiches[a_id], fiches[b_id]
        r = score_paire(a, b, max(frequences[tuple(a.cles)], frequences[tuple(b.cles)]))
        if r.score >= params.seuil_doublon_a_verifier - 0.1:
            retenues[(a_id, b_id)] = r

    # Ménage visité deux fois : plusieurs membres de deux ménages différents se correspondent.
    par_menages: dict[tuple[int, int], list[tuple[int, int]]] = defaultdict(list)
    for (a_id, b_id), r in retenues.items():
        ma, mb = fiches[a_id].menage_id, fiches[b_id].menage_id
        if ma != mb and r.details.get("nom", 1.0) >= 0.75:
            par_menages[(min(ma, mb), max(ma, mb))].append((a_id, b_id))
    for liste in par_menages.values():
        if len(liste) >= 2:
            for cle in liste:
                r = retenues[cle]
                r.score = round(min(1.0, r.score + 0.05 * min(len(liste) - 1, 3)), 4)
                r.details["menage_en_double"] = len(liste)

    return {k: r for k, r in retenues.items() if _niveau(r.score, params)}


def _enregistrer_paires(s: Session, resultats: dict[tuple[int, int], ResultatPaire], params: Parametres, perimetre: set[int] | None) -> int:
    """Met à jour les paires en base. Les paires déjà tranchées gardent leur décision."""
    req = select(PaireDoublon)
    if perimetre is not None:
        ids = list(perimetre)
        req = req.where(PaireDoublon.personne_a_id.in_(ids) | PaireDoublon.personne_b_id.in_(ids))
    existantes = {(p.personne_a_id, p.personne_b_id): p for p in s.scalars(req).all()}
    nouvelles = 0
    for (a_id, b_id), r in resultats.items():
        niveau = _niveau(r.score, params)
        existante = existantes.pop((a_id, b_id), None)
        if existante is None:
            s.add(PaireDoublon(personne_a_id=a_id, personne_b_id=b_id, score=r.score, niveau=niveau, details=json.dumps(r.details, ensure_ascii=False)))
            nouvelles += 1
        else:
            existante.score = r.score
            existante.niveau = niveau  # type: ignore[assignment]
            existante.details = json.dumps(r.details, ensure_ascii=False)
    # Les paires en attente qui ne ressortent plus (données corrigées) sont retirées.
    for p in existantes.values():
        if p.statut == "en_attente":
            s.delete(p)
    s.flush()
    return nouvelles


def recalculer_groupes(s: Session) -> int:
    """Regroupe les fiches d'une même personne (doublons probables non rejetés, ou confirmés)."""
    parent: dict[int, int] = {}

    def racine(x: int) -> int:
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    paires = s.execute(
        select(PaireDoublon.personne_a_id, PaireDoublon.personne_b_id, PaireDoublon.niveau, PaireDoublon.statut)
    ).all()
    for a_id, b_id, niveau, statut in paires:
        if statut == "confirme" or (niveau == "probable" and statut != "rejete"):
            ra, rb = racine(a_id), racine(b_id)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

    s.execute(update(Personne).values(groupe_id=Personne.id))
    groupes: dict[int, set[int]] = defaultdict(set)
    for x in list(parent):
        r = racine(x)
        groupes[r].update((x, r))
    for chef, membres in groupes.items():
        s.execute(update(Personne).where(Personne.id.in_(list(membres))).values(groupe_id=chef))
    s.flush()
    # Nombre de fiches en trop : dans chaque groupe, une seule fiche compte.
    return sum(len(m) - 1 for m in groupes.values())


def detecter_doublons(s: Session, params: Parametres) -> dict:
    """Recalcule tous les doublons de la base."""
    fiches = {f.id: f for f in charger_fiches(s)}
    paires = generer_candidats(list(fiches.values()))
    resultats = evaluer(fiches, paires, params)
    nouvelles = _enregistrer_paires(s, resultats, params, perimetre=None)
    fiches_en_trop = recalculer_groupes(s)
    return {
        "fiches": len(fiches),
        "paires_comparees": len(paires),
        "paires_retenues": len(resultats),
        "nouvelles_paires": nouvelles,
        "probables": sum(1 for r in resultats.values() if r.score >= params.seuil_doublon_probable),
        "fiches_en_double": fiches_en_trop,
    }


def verifier_menages(s: Session, menage_ids: list[int], params: Parametres) -> list[dict]:
    """Contrôle immédiat à la synchronisation : compare les membres de ces ménages à toute la base.

    Utilise la table des clés phonétiques pour ne charger que les fiches susceptibles de correspondre.
    """
    if not menage_ids:
        return []
    nouvelles = charger_fiches(s, list(s.scalars(select(Personne.id).where(Personne.menage_id.in_(menage_ids)))))
    if not nouvelles:
        return []
    ids_nouveaux = {f.id for f in nouvelles}
    cles = {p for f in nouvelles for p in prefixes(f)}
    nins = {f.nin for f in nouvelles if f.nin}
    ids_proches: set[int] = set()
    if cles:
        ids_proches |= set(s.scalars(select(CleNom.personne_id).where(CleNom.prefixe.in_(cles))))
    if nins:
        ids_proches |= set(s.scalars(select(Personne.id).where(Personne.nin_empreinte.in_(nins))))
    fiches = {f.id: f for f in charger_fiches(s, list(ids_proches | ids_nouveaux))}

    paires = {p for p in generer_candidats(list(fiches.values())) if p[0] in ids_nouveaux or p[1] in ids_nouveaux}
    resultats = evaluer(fiches, paires, params)
    _enregistrer_paires(s, resultats, params, perimetre=ids_nouveaux)
    recalculer_groupes(s)

    alertes = []
    for (a_id, b_id), r in sorted(resultats.items(), key=lambda kv: -kv[1].score):
        nouveau, autre = (a_id, b_id) if a_id in ids_nouveaux else (b_id, a_id)
        alertes.append(
            {
                "personne_id": nouveau,
                "menage_id": fiches[nouveau].menage_id,
                "correspond_a_personne_id": autre,
                "correspond_a_menage_id": fiches[autre].menage_id,
                "score": r.score,
                "niveau": _niveau(r.score, params),
                "details": r.details,
            }
        )
    return alertes


def supprimer_paires_orphelines(s: Session) -> None:
    ids = select(Personne.id)
    s.execute(delete(PaireDoublon).where(~PaireDoublon.personne_a_id.in_(ids) | ~PaireDoublon.personne_b_id.in_(ids)))
