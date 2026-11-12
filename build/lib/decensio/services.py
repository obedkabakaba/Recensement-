"""Opérations de haut niveau, partagées par la ligne de commande et l'API."""

from __future__ import annotations

import json
from pathlib import Path

from shapely.geometry import shape
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .anomalies import detecter_anomalies
from .config import Parametres
from .coverage import calculer_couverture
from .dedup import detecter_doublons, verifier_menages
from .geo import IndexZones, en_geojson, lire_zones, superficie_km2
from .ingest import MenageEntrant, enregistrer
from .models import EstimationPopulation, JournalAudit, LotImport, Menage, Zone
from .population import lire_tableau_estimations, somme_par_zone


def journaliser(s: Session, acteur: str, action: str, objet: str | None = None, details: dict | None = None) -> None:
    s.add(JournalAudit(acteur=acteur, action=action, objet=objet, details=json.dumps(details, ensure_ascii=False) if details else None))


def index_zones(s: Session) -> IndexZones:
    return IndexZones.depuis_geojson(s.execute(select(Zone.id, Zone.geometrie)).all())


def rattacher_menages(s: Session) -> int:
    """Recalcule la zone de chaque ménage à partir de son point GPS (après un import de zones)."""
    index = index_zones(s)
    n = 0
    for mid, lat, lon in s.execute(select(Menage.id, Menage.lat, Menage.lon)).all():
        s.execute(update(Menage).where(Menage.id == mid).values(zone_id=index.zone_du_point(lat, lon)))
        n += 1
    return n


def importer_zones(
    s: Session,
    chemin: str | Path,
    niveau: str = "quartier",
    champ_code: str | None = None,
    champ_nom: str | None = None,
    champ_parent: str | None = None,
) -> dict:
    entites = lire_zones(chemin, niveau, champ_code, champ_nom, champ_parent)
    existantes = {z.code: z for z in s.scalars(select(Zone)).all()}
    crees = maj = 0
    for e in entites:
        z = existantes.get(e.code)
        if z is None:
            z = Zone(code=e.code)
            s.add(z)
            crees += 1
        else:
            maj += 1
        z.nom = e.nom
        z.niveau = e.niveau
        z.code_parent = e.code_parent
        z.geometrie = en_geojson(e.geometrie)
        z.superficie_km2 = round(superficie_km2(e.geometrie), 4)
        c = e.geometrie.representative_point()
        z.lat, z.lon = c.y, c.x
    s.flush()
    rattaches = rattacher_menages(s)
    return {"zones_creees": crees, "zones_mises_a_jour": maj, "menages_rattaches": rattaches}


def _enregistrer_estimation(s: Session, zone_id: int, source: str, population: float, basse=None, haute=None, date_reference=None) -> None:
    e = s.scalar(select(EstimationPopulation).where(EstimationPopulation.zone_id == zone_id, EstimationPopulation.source == source))
    if e is None:
        e = EstimationPopulation(zone_id=zone_id, source=source, population=population)
        s.add(e)
    e.population = population
    e.borne_basse = basse
    e.borne_haute = haute
    e.date_reference = date_reference


def importer_grille(s: Session, chemin: str | Path, source: str = "GRID3", niveau: str | None = None, date_reference: str | None = None) -> dict:
    """Calcule la population de chaque zone à partir d'une grille (GeoTIFF GRID3 ou WorldPop)."""
    req = select(Zone)
    if niveau:
        req = req.where(Zone.niveau == niveau)
    zones = list(s.scalars(req).all())
    sommes = somme_par_zone(chemin, {z.code: shape(json.loads(z.geometrie)) for z in zones})
    total = 0.0
    for z in zones:
        somme = sommes.get(z.code)
        if somme is None:
            continue
        _enregistrer_estimation(s, z.id, source, round(somme.population, 1), date_reference=date_reference)
        total += somme.population
    s.flush()
    return {"zones": len(zones), "population_totale": round(total)}


def importer_estimations_csv(s: Session, chemin: str | Path, source: str, date_reference: str | None = None) -> dict:
    """Importe des estimations déjà calculées (RGPH-2, projections INS…) : code_zone ; population."""
    zones = {z.code: z.id for z in s.scalars(select(Zone)).all()}
    importees, inconnues = 0, []
    for ligne in lire_tableau_estimations(chemin):
        zid = zones.get(ligne.code_zone)
        if zid is None:
            inconnues.append(ligne.code_zone)
            continue
        _enregistrer_estimation(s, zid, source, ligne.population, ligne.borne_basse, ligne.borne_haute, date_reference)
        importees += 1
    s.flush()
    return {"estimations_importees": importees, "codes_inconnus": inconnues[:50], "nb_codes_inconnus": len(inconnues)}


def importer_menages(s: Session, menages: list[MenageEntrant], params: Parametres, source: str, fichier: str | None = None) -> tuple[LotImport, list[Menage]]:
    return enregistrer(s, menages, params, index_zones(s), source=source, fichier=fichier)


def synchroniser(s: Session, menages: list[MenageEntrant], params: Parametres, source: str = "sync") -> dict:
    """Synchronisation d'une tablette : enregistre, puis renvoie aussitôt les alertes de doublon."""
    lot, enregistres = importer_menages(s, menages, params, source)
    alertes = verifier_menages(s, [m.id for m in enregistres], params)
    par_externe = {m.id: m.identifiant_externe for m in enregistres}
    ids_menages = {a["correspond_a_menage_id"] for a in alertes}
    externes = dict(s.execute(select(Menage.id, Menage.identifiant_externe).where(Menage.id.in_(ids_menages))).all()) if ids_menages else {}
    for a in alertes:
        a["menage"] = par_externe.get(a["menage_id"])
        a["correspond_a_menage"] = externes.get(a["correspond_a_menage_id"])
    return {"lot_id": lot.id, "menages": len(enregistres), "personnes": lot.nb_personnes, "alertes_doublons": alertes}


def recalculer(s: Session, params: Parametres) -> dict:
    """Recalcule tout : doublons, puis saisies suspectes, puis couverture (qui dépend des doublons)."""
    doublons = detecter_doublons(s, params)
    anomalies = detecter_anomalies(s, params)
    couverture = calculer_couverture(s, params)
    return {"doublons": doublons, "anomalies": anomalies, "couverture": couverture}
