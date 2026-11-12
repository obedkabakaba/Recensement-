"""Import des ménages et des personnes enregistrés (export CSPro, fichier d'enrôlement, synchronisation).

Deux formats d'entrée :
- CSV « à plat » : une ligne par personne, les colonnes du ménage étant répétées ;
- JSON : une liste de ménages, chacun avec ses membres (format de l'API /api/sync).

Les noms de colonnes courants des exports CSPro, ODK/Kobo et des fichiers d'enrôlement
sont reconnus automatiquement (voir ALIAS).
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Parametres
from .geo import IndexZones
from .models import CleNom, LotImport, Menage, Personne
from .noms import cles_phonetiques, empreinte_nin, jetons_nom

ALIAS: dict[str, list[str]] = {
    "menage_id": ["menage_id", "id_menage", "identifiant_menage", "numero_menage", "household_id", "hh_id", "menage"],
    "agent_id": ["agent_id", "agent", "enqueteur", "code_agent", "interviewer_id", "enumerator"],
    "appareil_id": ["appareil_id", "appareil", "tablette", "device_id", "deviceid"],
    "date_collecte": ["date_collecte", "collecte_le", "date_heure", "date_interview", "timestamp", "start_time", "start"],
    "latitude": ["latitude", "lat", "gps_lat", "gps_latitude", "_gps_latitude"],
    "longitude": ["longitude", "lon", "lng", "gps_lon", "gps_longitude", "_gps_longitude"],
    "precision_gps": ["precision_gps", "precision_gps_m", "gps_precision", "accuracy", "_gps_precision"],
    "zone_assignee": ["zone_assignee", "code_zone", "zone_code", "aire_denombrement", "zd", "code_zd", "quartier_code"],
    "taille_menage": ["taille_menage", "taille_declaree", "nb_membres", "household_size", "hh_size"],
    "personne_id": ["personne_id", "id_personne", "person_id", "identifiant_personne"],
    "rang": ["rang", "ligne", "numero_ligne", "line", "line_number"],
    "nom": ["nom", "last_name", "surname", "nom_famille"],
    "postnom": ["postnom", "post_nom", "middle_name"],
    "prenom": ["prenom", "first_name", "given_name"],
    "sexe": ["sexe", "sex", "genre", "gender"],
    "date_naissance": ["date_naissance", "date_de_naissance", "dob", "birth_date", "naissance"],
    "age": ["age", "age_annees", "age_years"],
    "lien": ["lien", "lien_parente", "lien_cm", "relationship", "relation"],
    "nin": ["nin", "numero_identification", "numero_national", "national_id"],
}

LIENS = {
    "1": "chef", "chef": "chef", "cm": "chef", "chef de menage": "chef", "chef_menage": "chef", "head": "chef",
    "2": "conjoint", "conjoint": "conjoint", "epoux": "conjoint", "epouse": "conjoint", "spouse": "conjoint",
    "3": "enfant", "enfant": "enfant", "fils": "enfant", "fille": "enfant", "child": "enfant",
    "4": "parent", "parent": "parent", "pere": "parent", "mere": "parent",
    "5": "autre_parent", "petit-enfant": "autre_parent", "frere": "autre_parent", "soeur": "autre_parent",
    "6": "sans_lien", "autre": "sans_lien", "sans lien": "sans_lien",
}


@dataclass
class PersonneEntrante:
    rang: int
    nom: str | None = None
    postnom: str | None = None
    prenom: str | None = None
    sexe: str | None = None
    date_naissance: date | None = None
    age: int | None = None
    lien: str | None = None
    nin: str | None = None
    identifiant: str | None = None


@dataclass
class MenageEntrant:
    identifiant: str
    agent_id: str | None = None
    appareil_id: str | None = None
    collecte_le: datetime | None = None
    lat: float | None = None
    lon: float | None = None
    precision_gps_m: float | None = None
    zone_assignee: str | None = None
    taille_declaree: int | None = None
    membres: list[PersonneEntrante] = field(default_factory=list)


# ---------------------------------------------------------------- conversions


def _texte(v: Any) -> str | None:
    if v is None:
        return None
    v = str(v).strip()
    return v or None


def _nombre(v: Any) -> float | None:
    v = _texte(v)
    if v is None:
        return None
    try:
        return float(v.replace(",", ".").replace(" ", ""))
    except ValueError:
        return None


def _entier(v: Any) -> int | None:
    n = _nombre(v)
    return int(n) if n is not None else None


def lire_sexe(v: Any) -> str | None:
    v = (_texte(v) or "").lower()
    if v in {"m", "h", "1", "masculin", "homme", "male", "garcon"}:
        return "M"
    if v in {"f", "2", "feminin", "féminin", "femme", "female", "fille"}:
        return "F"
    return None


def lire_lien(v: Any) -> str | None:
    v = (_texte(v) or "").lower()
    if not v:
        return None
    return LIENS.get(v, v)


def lire_date(v: Any) -> date | None:
    v = _texte(v)
    if not v:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d", "%Y%m%d"):
        try:
            return datetime.strptime(v[:10], fmt).date()
        except ValueError:
            continue
    return None


def lire_horodatage(v: Any, decalage_heures: int = 1) -> datetime | None:
    """Lit une date-heure ; sans fuseau, on suppose l'heure locale (Kinshasa : UTC+1)."""
    if isinstance(v, datetime):
        dt = v
    else:
        v = _texte(v)
        if not v:
            return None
        dt = None
        try:
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y"):
                try:
                    dt = datetime.strptime(v, fmt)
                    break
                except ValueError:
                    continue
        if dt is None:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone(timedelta(hours=decalage_heures)))
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------- lecture des fichiers


def _correspondance_colonnes(entetes: Iterable[str], personnalisee: dict[str, str] | None) -> dict[str, str]:
    entetes_min = {h.strip().lower(): h for h in entetes if h}
    correspondance: dict[str, str] = {}
    for champ, alias in ALIAS.items():
        if personnalisee and champ in personnalisee:
            correspondance[champ] = personnalisee[champ]
            continue
        for a in alias:
            if a in entetes_min:
                correspondance[champ] = entetes_min[a]
                break
    return correspondance


def lire_csv(chemin: str | Path, colonnes: dict[str, str] | None = None, decalage_heures: int = 1) -> list[MenageEntrant]:
    """Lit un fichier CSV « une ligne par personne » et regroupe les lignes par ménage."""
    return lire_csv_texte(Path(chemin).read_text(encoding="utf-8-sig"), colonnes, decalage_heures)


def lire_csv_texte(texte: str, colonnes: dict[str, str] | None = None, decalage_heures: int = 1) -> list[MenageEntrant]:
    """Même lecture à partir du contenu du fichier (téléversement par l'API)."""
    texte = texte.lstrip("\ufeff")
    premiere = texte.splitlines()[0] if texte else ""
    separateur = ";" if premiere.count(";") > premiere.count(",") else ","
    lecteur = csv.DictReader(io.StringIO(texte), delimiter=separateur)
    c = _correspondance_colonnes(lecteur.fieldnames or [], colonnes)
    if "menage_id" not in c:
        raise ValueError("Colonne d'identifiant de ménage introuvable (menage_id, id_menage, household_id…).")

    def val(ligne: dict, champ: str) -> Any:
        col = c.get(champ)
        return ligne.get(col) if col else None

    menages: dict[str, MenageEntrant] = {}
    for ligne in lecteur:
        ident = _texte(val(ligne, "menage_id"))
        if not ident:
            continue
        m = menages.get(ident)
        if m is None:
            m = MenageEntrant(
                identifiant=ident,
                agent_id=_texte(val(ligne, "agent_id")),
                appareil_id=_texte(val(ligne, "appareil_id")),
                collecte_le=lire_horodatage(val(ligne, "date_collecte"), decalage_heures),
                lat=_nombre(val(ligne, "latitude")),
                lon=_nombre(val(ligne, "longitude")),
                precision_gps_m=_nombre(val(ligne, "precision_gps")),
                zone_assignee=_texte(val(ligne, "zone_assignee")),
                taille_declaree=_entier(val(ligne, "taille_menage")),
            )
            menages[ident] = m
        if not any(_texte(val(ligne, k)) for k in ("nom", "postnom", "prenom", "sexe", "age", "date_naissance", "nin")):
            continue  # ligne de ménage sans membre
        m.membres.append(
            PersonneEntrante(
                rang=_entier(val(ligne, "rang")) or len(m.membres) + 1,
                nom=_texte(val(ligne, "nom")),
                postnom=_texte(val(ligne, "postnom")),
                prenom=_texte(val(ligne, "prenom")),
                sexe=lire_sexe(val(ligne, "sexe")),
                date_naissance=lire_date(val(ligne, "date_naissance")),
                age=_entier(val(ligne, "age")),
                lien=lire_lien(val(ligne, "lien")),
                nin=_texte(val(ligne, "nin")),
                identifiant=_texte(val(ligne, "personne_id")),
            )
        )
    return list(menages.values())


def menages_depuis_json(donnees: dict | list, decalage_heures: int = 1) -> list[MenageEntrant]:
    """Convertit le format JSON (liste de ménages avec leurs membres)."""
    liste = donnees.get("menages", []) if isinstance(donnees, dict) else donnees
    resultat: list[MenageEntrant] = []
    for m in liste:
        membres = [
            PersonneEntrante(
                rang=_entier(p.get("rang")) or i,
                nom=_texte(p.get("nom")),
                postnom=_texte(p.get("postnom")),
                prenom=_texte(p.get("prenom")),
                sexe=lire_sexe(p.get("sexe")),
                date_naissance=lire_date(p.get("date_naissance")),
                age=_entier(p.get("age")),
                lien=lire_lien(p.get("lien")),
                nin=_texte(p.get("nin")),
                identifiant=_texte(p.get("identifiant")),
            )
            for i, p in enumerate(m.get("membres", []), start=1)
        ]
        resultat.append(
            MenageEntrant(
                identifiant=str(m["identifiant"]),
                agent_id=_texte(m.get("agent_id")),
                appareil_id=_texte(m.get("appareil_id")),
                collecte_le=lire_horodatage(m.get("collecte_le"), decalage_heures),
                lat=_nombre(m.get("lat")),
                lon=_nombre(m.get("lon")),
                precision_gps_m=_nombre(m.get("precision_gps_m")),
                zone_assignee=_texte(m.get("zone_assignee")),
                taille_declaree=_entier(m.get("taille_declaree")),
                membres=membres,
            )
        )
    return resultat


def lire_json(chemin: str | Path, decalage_heures: int = 1) -> list[MenageEntrant]:
    return menages_depuis_json(json.loads(Path(chemin).read_text(encoding="utf-8")), decalage_heures)


# ---------------------------------------------------------------- enregistrement


def _annee_naissance(p: PersonneEntrante, collecte: datetime | None) -> int | None:
    if p.date_naissance:
        return p.date_naissance.year
    if p.age is not None and 0 <= p.age <= 130:
        annee_ref = collecte.year if collecte else datetime.now(timezone.utc).year
        return annee_ref - p.age
    return None


def construire_personne(p: PersonneEntrante, collecte: datetime | None, params: Parametres) -> Personne:
    nom_affiche = " ".join(x for x in (p.nom, p.postnom, p.prenom) if x) if params.stocker_noms else None
    age = p.age
    if age is None and p.date_naissance and collecte:
        d = collecte.date()
        age = d.year - p.date_naissance.year - ((d.month, d.day) < (p.date_naissance.month, p.date_naissance.day))
    cles = cles_phonetiques(p.nom, p.postnom, p.prenom)
    return Personne(
        cles=[CleNom(cle=c, prefixe=c[:4]) for c in cles],
        identifiant_externe=p.identifiant,
        rang=p.rang,
        nom_affiche=nom_affiche or None,
        cles_phonetiques=" ".join(cles),
        jetons_nom=" ".join(jetons_nom(params.secret, p.nom, p.postnom, p.prenom)),
        sexe=p.sexe,
        date_naissance=p.date_naissance,
        annee_naissance=_annee_naissance(p, collecte),
        age=age,
        lien=p.lien,
        nin_empreinte=empreinte_nin(p.nin, params.secret),
    )


def enregistrer(
    s: Session,
    menages: list[MenageEntrant],
    params: Parametres,
    index: IndexZones,
    source: str = "csv",
    fichier: str | None = None,
) -> tuple[LotImport, list[Menage]]:
    """Enregistre les ménages ; un ménage déjà connu (même identifiant) est mis à jour."""
    lot = LotImport(source=source, fichier=fichier)
    s.add(lot)
    s.flush()
    identifiants = [m.identifiant for m in menages]
    existants = {
        m.identifiant_externe: m
        for m in s.scalars(select(Menage).where(Menage.identifiant_externe.in_(identifiants))).all()
    } if identifiants else {}

    enregistres: list[Menage] = []
    nb_personnes = 0
    for m in menages:
        menage = existants.get(m.identifiant)
        if menage is None:
            menage = Menage(identifiant_externe=m.identifiant)
            s.add(menage)
        else:
            menage.personnes.clear()
        menage.lot_id = lot.id
        menage.agent_id = m.agent_id
        menage.appareil_id = m.appareil_id
        menage.collecte_le = m.collecte_le
        menage.lat, menage.lon = m.lat, m.lon
        menage.precision_gps_m = m.precision_gps_m
        menage.zone_assignee_code = m.zone_assignee
        menage.taille_declaree = m.taille_declaree
        menage.zone_id = index.zone_du_point(m.lat, m.lon)
        for p in m.membres:
            menage.personnes.append(construire_personne(p, m.collecte_le, params))
        nb_personnes += len(m.membres)
        enregistres.append(menage)

    lot.nb_menages = len(menages)
    lot.nb_personnes = nb_personnes
    s.flush()
    return lot, enregistres

