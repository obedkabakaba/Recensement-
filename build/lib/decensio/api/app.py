"""API web de Decensio et tableau de bord.

Lancement : decensio serveur   (ou : uvicorn decensio.api.app:app)
Documentation interactive : /docs
"""

from __future__ import annotations

import json
import tempfile
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from .. import __version__
from ..anomalies import LIBELLES, detecter_anomalies
from ..config import parametres
from ..coverage import calculer_couverture
from ..db import initialiser_base, nouvelle_session
from ..dedup import recalculer_groupes
from ..ingest import lire_csv_texte, menages_depuis_json
from ..models import (
    Anomalie,
    CouvertureZone,
    JournalAudit,
    Menage,
    PaireDoublon,
    Personne,
    Zone,
)
from ..services import (
    importer_estimations_csv,
    importer_menages,
    importer_zones,
    journaliser,
    recalculer,
    synchroniser,
)

STATIQUE = Path(__file__).resolve().parent.parent / "web" / "static"

@asynccontextmanager
async def _cycle_de_vie(_: FastAPI):
    initialiser_base()
    yield


app = FastAPI(
    title="Decensio",
    version=__version__,
    description="Couverture et contrôle qualité du recensement et de l'identification. Chaque personne, une seule fois.",
    lifespan=_cycle_de_vie,
)


def get_session():
    s = nouvelle_session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def ecriture_autorisee(x_cle_api: str | None = Header(default=None), x_utilisateur: str | None = Header(default=None)) -> str:
    """Les routes qui modifient des données exigent la clé d'API (en-tête X-Cle-API) si elle est définie."""
    cle = parametres().api_key
    if cle and x_cle_api != cle:
        raise HTTPException(status_code=401, detail="Clé d'API absente ou invalide (en-tête X-Cle-API).")
    return x_utilisateur or "api"


# ---------------------------------------------------------------- schémas


class MembreSync(BaseModel):
    rang: int | None = None
    nom: str | None = None
    postnom: str | None = None
    prenom: str | None = None
    sexe: str | None = None
    date_naissance: str | None = None
    age: int | None = None
    lien: str | None = None
    nin: str | None = None
    identifiant: str | None = None


class MenageSync(BaseModel):
    identifiant: str
    agent_id: str | None = None
    appareil_id: str | None = None
    collecte_le: str | None = None
    lat: float | None = None
    lon: float | None = None
    precision_gps_m: float | None = None
    zone_assignee: str | None = None
    taille_declaree: int | None = None
    membres: list[MembreSync] = Field(default_factory=list)


class LotSync(BaseModel):
    menages: list[MenageSync]


class Decision(BaseModel):
    decision: Literal["confirme", "rejete", "en_attente"]
    commentaire: str | None = None


class StatutAnomalie(BaseModel):
    statut: Literal["ouverte", "justifiee", "corrigee"]
    commentaire: str | None = None


# ---------------------------------------------------------------- lecture


@app.get("/api/sante")
def sante() -> dict:
    return {"statut": "ok", "version": __version__, "heure": datetime.now(timezone.utc).isoformat()}


@app.get("/api/resume")
def resume(s: Session = Depends(get_session)) -> dict:
    statuts = dict(s.execute(select(CouvertureZone.statut, func.count()).group_by(CouvertureZone.statut)).all())
    gravites = dict(s.execute(select(Anomalie.gravite, func.count()).where(Anomalie.statut == "ouverte").group_by(Anomalie.gravite)).all())
    doublons = dict(s.execute(select(PaireDoublon.niveau, func.count()).where(PaireDoublon.statut == "en_attente").group_by(PaireDoublon.niveau)).all())
    personnes = s.scalar(select(func.count(Personne.id))) or 0
    uniques = s.scalar(select(func.count(Personne.id)).where((Personne.groupe_id.is_(None)) | (Personne.groupe_id == Personne.id))) or 0
    # Population attendue : somme des zones sans parent connu (niveau le plus haut).
    codes = set(s.scalars(select(Zone.code)))
    racines = [z for z in s.scalars(select(Zone)).all() if not z.code_parent or z.code_parent not in codes]
    attendus = 0.0
    for z in racines:
        c = s.scalar(select(CouvertureZone).where(CouvertureZone.zone_id == z.id))
        if c and c.population_estimee:
            attendus += c.population_estimee
    return {
        "zones": s.scalar(select(func.count(Zone.id))) or 0,
        "menages": s.scalar(select(func.count(Menage.id))) or 0,
        "personnes": personnes,
        "personnes_uniques": uniques,
        "population_attendue": round(attendus),
        "taux_global": round(uniques / attendus, 4) if attendus else None,
        "zones_par_statut": statuts,
        "doublons_en_attente": doublons,
        "anomalies_ouvertes": gravites,
        "stocke_noms": parametres().stocker_noms,
        "dernier_calcul": s.scalar(select(func.max(CouvertureZone.calcule_le))),
    }


def _ligne_couverture(z: Zone, c: CouvertureZone | None) -> dict:
    return {
        "id": z.id,
        "code": z.code,
        "nom": z.nom,
        "niveau": z.niveau,
        "code_parent": z.code_parent,
        "superficie_km2": z.superficie_km2,
        "population_estimee": round(c.population_estimee) if c and c.population_estimee is not None else None,
        "source_estimation": c.source_estimation if c else None,
        "menages": c.menages if c else 0,
        "personnes_enregistrees": c.personnes_enregistrees if c else 0,
        "personnes_uniques": c.personnes_uniques if c else 0,
        "manquants": max(0, round((c.population_estimee or 0) - c.personnes_uniques)) if c and c.population_estimee is not None else None,
        "taux": c.taux if c else None,
        "statut": c.statut if c else "non_calcule",
    }


def _zones_couverture(s: Session, niveau: str | None):
    req = select(Zone, CouvertureZone).outerjoin(CouvertureZone, CouvertureZone.zone_id == Zone.id)
    if niveau:
        req = req.where(Zone.niveau == niveau)
    return s.execute(req.order_by(Zone.code)).all()


@app.get("/api/niveaux")
def niveaux(s: Session = Depends(get_session)) -> list[dict]:
    return [{"niveau": n, "zones": c} for n, c in s.execute(select(Zone.niveau, func.count()).group_by(Zone.niveau)).all()]


@app.get("/api/couverture")
def couverture(niveau: str | None = None, s: Session = Depends(get_session)) -> list[dict]:
    return [_ligne_couverture(z, c) for z, c in _zones_couverture(s, niveau)]


@app.get("/api/zones.geojson")
def zones_geojson(niveau: str | None = None, s: Session = Depends(get_session)) -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "properties": _ligne_couverture(z, c), "geometry": json.loads(z.geometrie)}
            for z, c in _zones_couverture(s, niveau)
        ],
    }


def heure_locale(dt: datetime | None) -> str | None:
    """Date-heure en heure locale (les bases SQLite renvoient de l'UTC sans fuseau)."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone(timedelta(hours=parametres().decalage_horaire))).isoformat()


def _resume_personne(p: Personne, m: Menage, zones: dict[int, Zone]) -> dict:
    z = zones.get(m.zone_id) if m.zone_id else None
    return {
        "id": p.id,
        "nom": p.nom_affiche,
        "cles": p.cles_phonetiques,
        "sexe": p.sexe,
        "date_naissance": p.date_naissance.isoformat() if p.date_naissance else None,
        "annee_naissance": p.annee_naissance,
        "age": p.age,
        "lien": p.lien,
        "menage": m.identifiant_externe,
        "menage_id": m.id,
        "agent_id": m.agent_id,
        "collecte_le": heure_locale(m.collecte_le),
        "zone": z.nom if z else None,
        "lat": m.lat,
        "lon": m.lon,
    }


@app.get("/api/doublons")
def doublons(
    statut: str = "en_attente",
    niveau: str | None = None,
    limite: int = Query(100, le=1000),
    decalage: int = 0,
    s: Session = Depends(get_session),
) -> dict:
    PA, PB = aliased(Personne), aliased(Personne)
    MA, MB = aliased(Menage), aliased(Menage)
    req = (
        select(PaireDoublon, PA, MA, PB, MB)
        .join(PA, PA.id == PaireDoublon.personne_a_id).join(MA, MA.id == PA.menage_id)
        .join(PB, PB.id == PaireDoublon.personne_b_id).join(MB, MB.id == PB.menage_id)
    )
    if statut != "tous":
        req = req.where(PaireDoublon.statut == statut)
    if niveau:
        req = req.where(PaireDoublon.niveau == niveau)
    total = s.scalar(select(func.count()).select_from(req.subquery()))
    lignes = s.execute(req.order_by(PaireDoublon.score.desc()).offset(decalage).limit(limite)).all()
    zones = {z.id: z for z in s.scalars(select(Zone)).all()}
    return {
        "total": total,
        "paires": [
            {
                "id": d.id, "score": d.score, "niveau": d.niveau, "statut": d.statut, "details": json.loads(d.details or "{}"),
                "commentaire": d.commentaire, "decide_par": d.decide_par,
                "a": _resume_personne(pa, ma, zones), "b": _resume_personne(pb, mb, zones),
            }
            for d, pa, ma, pb, mb in lignes
        ],
    }


@app.get("/api/doublons/menages")
def menages_en_double(s: Session = Depends(get_session)) -> list[dict]:
    """Ménages qui partagent au moins deux personnes en double : probablement visités deux fois."""
    PA, PB = aliased(Personne), aliased(Personne)
    lignes = s.execute(
        select(PA.menage_id, PB.menage_id, PaireDoublon.score)
        .join(PA, PA.id == PaireDoublon.personne_a_id)
        .join(PB, PB.id == PaireDoublon.personne_b_id)
        .where(PaireDoublon.statut != "rejete", PA.menage_id != PB.menage_id)
    ).all()
    groupes: dict[tuple[int, int], list[float]] = defaultdict(list)
    for a, b, score in lignes:
        groupes[(min(a, b), max(a, b))].append(score)
    ids = {i for k in groupes for i in k}
    menages = {m.id: m for m in s.scalars(select(Menage).where(Menage.id.in_(ids)))} if ids else {}
    resultat = []
    for (a, b), scores in groupes.items():
        if len(scores) < 2:
            continue
        ma, mb = menages[a], menages[b]
        resultat.append({
            "menage_a": ma.identifiant_externe, "agent_a": ma.agent_id, "menage_b": mb.identifiant_externe, "agent_b": mb.agent_id,
            "personnes_communes": len(scores), "score_moyen": round(sum(scores) / len(scores), 3),
        })
    return sorted(resultat, key=lambda r: (-r["personnes_communes"], -r["score_moyen"]))


@app.get("/api/anomalies")
def anomalies(
    statut: str = "ouverte",
    gravite: str | None = None,
    type: str | None = None,
    agent: str | None = None,
    limite: int = Query(200, le=2000),
    decalage: int = 0,
    s: Session = Depends(get_session),
) -> dict:
    req = select(Anomalie, Menage).outerjoin(Menage, Menage.id == Anomalie.menage_id)
    if statut != "toutes":
        req = req.where(Anomalie.statut == statut)
    if gravite:
        req = req.where(Anomalie.gravite == gravite)
    if type:
        req = req.where(Anomalie.type == type)
    if agent:
        req = req.where(Anomalie.agent_id == agent)
    total = s.scalar(select(func.count()).select_from(req.subquery()))
    ordre = {"haute": 0, "moyenne": 1, "basse": 2}
    lignes = s.execute(req.offset(decalage).limit(limite)).all()
    lignes = sorted(lignes, key=lambda l: (ordre.get(l[0].gravite, 3), l[0].type))
    return {
        "total": total,
        "anomalies": [
            {
                "id": a.id, "type": a.type, "libelle": LIBELLES.get(a.type, a.type), "gravite": a.gravite, "cible": a.cible,
                "message": a.message, "detail": a.message.split(" : ", 1)[1] if " : " in a.message else None, "valeur": a.valeur, "statut": a.statut, "agent_id": a.agent_id,
                "menage": m.identifiant_externe if m else None, "lat": m.lat if m else None, "lon": m.lon if m else None,
            }
            for a, m in lignes
        ],
    }


@app.get("/api/agents")
def agents(s: Session = Depends(get_session)) -> list[dict]:
    """Tableau de suivi des agents : volume, anomalies et doublons."""
    stats: dict[str, dict] = defaultdict(lambda: {"menages": 0, "personnes": 0, "anomalies": 0, "anomalies_hautes": 0, "doublons": 0})
    for agent, nb in s.execute(select(Menage.agent_id, func.count()).group_by(Menage.agent_id)):
        stats[agent or "—"]["menages"] = nb
    for agent, nb in s.execute(select(Menage.agent_id, func.count(Personne.id)).join(Personne).group_by(Menage.agent_id)):
        stats[agent or "—"]["personnes"] = nb
    for agent, gravite, nb in s.execute(select(Anomalie.agent_id, Anomalie.gravite, func.count()).where(Anomalie.statut == "ouverte").group_by(Anomalie.agent_id, Anomalie.gravite)):
        stats[agent or "—"]["anomalies"] += nb
        if gravite == "haute":
            stats[agent or "—"]["anomalies_hautes"] += nb
    PB = aliased(Personne)
    MB = aliased(Menage)
    for agent, nb in s.execute(
        select(MB.agent_id, func.count()).select_from(PaireDoublon)
        .join(PB, PB.id == PaireDoublon.personne_b_id).join(MB, MB.id == PB.menage_id)
        .where(PaireDoublon.statut != "rejete").group_by(MB.agent_id)
    ):
        stats[agent or "—"]["doublons"] += nb
    resultat = []
    for agent, v in stats.items():
        v["taux_anomalies"] = round(v["anomalies"] / v["menages"], 3) if v["menages"] else None
        resultat.append({"agent_id": agent, **v})
    return sorted(resultat, key=lambda r: (-r["anomalies_hautes"], -(r["taux_anomalies"] or 0)))


@app.get("/api/journal")
def journal(limite: int = Query(100, le=1000), s: Session = Depends(get_session)) -> list[dict]:
    return [
        {"horodatage": j.horodatage, "acteur": j.acteur, "action": j.action, "objet": j.objet, "details": json.loads(j.details) if j.details else None}
        for j in s.scalars(select(JournalAudit).order_by(JournalAudit.id.desc()).limit(limite))
    ]


# ---------------------------------------------------------------- écriture


@app.post("/api/sync")
def sync(lot: LotSync, s: Session = Depends(get_session), acteur: str = Depends(ecriture_autorisee)) -> dict:
    """Synchronisation d'une tablette : enregistre les ménages et renvoie aussitôt les alertes de doublon."""
    p = parametres()
    menages = menages_depuis_json(lot.model_dump(), p.decalage_horaire)
    r = synchroniser(s, menages, p)
    journaliser(s, acteur, "sync", None, {"menages": r["menages"], "alertes": len(r["alertes_doublons"])})
    return r


@app.post("/api/doublons/{paire_id}/decision")
def decider_doublon(paire_id: int, d: Decision, s: Session = Depends(get_session), acteur: str = Depends(ecriture_autorisee)) -> dict:
    paire = s.get(PaireDoublon, paire_id)
    if paire is None:
        raise HTTPException(404, "Paire introuvable.")
    paire.statut = d.decision
    paire.commentaire = d.commentaire
    paire.decide_par = acteur
    paire.decide_le = datetime.now(timezone.utc)
    s.flush()
    recalculer_groupes(s)
    calculer_couverture(s, parametres())
    journaliser(s, acteur, "decision_doublon", f"paire:{paire_id}", {"decision": d.decision})
    return {"id": paire_id, "statut": paire.statut}


@app.post("/api/anomalies/{anomalie_id}/statut")
def changer_statut_anomalie(anomalie_id: int, d: StatutAnomalie, s: Session = Depends(get_session), acteur: str = Depends(ecriture_autorisee)) -> dict:
    a = s.get(Anomalie, anomalie_id)
    if a is None:
        raise HTTPException(404, "Anomalie introuvable.")
    a.statut = d.statut
    journaliser(s, acteur, "statut_anomalie", f"anomalie:{anomalie_id}", {"statut": d.statut, "commentaire": d.commentaire})
    return {"id": anomalie_id, "statut": a.statut}


@app.post("/api/recalcul")
def lancer_recalcul(s: Session = Depends(get_session), acteur: str = Depends(ecriture_autorisee)) -> dict:
    r = recalculer(s, parametres())
    journaliser(s, acteur, "recalcul", None, r)
    return r


@app.post("/api/import/enregistrements")
async def import_enregistrements(
    fichier: UploadFile = File(...),
    source: str = Form("csv"),
    s: Session = Depends(get_session),
    acteur: str = Depends(ecriture_autorisee),
) -> dict:
    p = parametres()
    contenu = (await fichier.read()).decode("utf-8-sig")
    nom = fichier.filename or "fichier"
    menages = menages_depuis_json(json.loads(contenu), p.decalage_horaire) if nom.lower().endswith(".json") else lire_csv_texte(contenu, None, p.decalage_horaire)
    lot, _ = importer_menages(s, menages, p, source, nom)
    calcul = recalculer(s, p)
    journaliser(s, acteur, "import_enregistrements", nom, {"menages": lot.nb_menages, "personnes": lot.nb_personnes})
    return {"lot": lot.id, "menages": lot.nb_menages, "personnes": lot.nb_personnes, "calcul": calcul}


async def _fichier_temporaire(f: UploadFile, suffixe: str) -> Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffixe)
    tmp.write(await f.read())
    tmp.close()
    return Path(tmp.name)


@app.post("/api/import/zones")
async def import_zones(
    fichier: UploadFile = File(...),
    niveau: str = Form("quartier"),
    s: Session = Depends(get_session),
    acteur: str = Depends(ecriture_autorisee),
) -> dict:
    chemin = await _fichier_temporaire(fichier, Path(fichier.filename or "zones.geojson").suffix or ".geojson")
    try:
        r = importer_zones(s, chemin, niveau)
    finally:
        chemin.unlink(missing_ok=True)
    calculer_couverture(s, parametres())
    detecter_anomalies(s, parametres())
    journaliser(s, acteur, "import_zones", fichier.filename, r)
    return r


@app.post("/api/import/estimations")
async def import_estimations(
    fichier: UploadFile = File(...),
    source: str = Form(...),
    s: Session = Depends(get_session),
    acteur: str = Depends(ecriture_autorisee),
) -> dict:
    chemin = await _fichier_temporaire(fichier, ".csv")
    try:
        r = importer_estimations_csv(s, chemin, source)
    finally:
        chemin.unlink(missing_ok=True)
    calculer_couverture(s, parametres())
    journaliser(s, acteur, "import_estimations", fichier.filename, {"importees": r["estimations_importees"]})
    return r


# ---------------------------------------------------------------- tableau de bord

if STATIQUE.exists():
    app.mount("/static", StaticFiles(directory=STATIQUE), name="static")


@app.get("/", include_in_schema=False)
def accueil() -> FileResponse:
    return FileResponse(STATIQUE / "index.html")
