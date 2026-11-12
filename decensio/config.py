"""Paramètres de Decensio, lus dans les variables d'environnement (préfixe DECENSIO_)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _charger_fichier_env(chemin: Path = Path(".env")) -> None:
    """Charge un fichier .env simple (CLE=valeur) sans écraser l'environnement existant."""
    if not chemin.exists():
        return
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, valeur = ligne.split("=", 1)
        os.environ.setdefault(cle.strip(), valeur.strip())


def _float(nom: str, defaut: float) -> float:
    return float(os.environ.get(nom, defaut))


def _bool(nom: str, defaut: bool) -> bool:
    return os.environ.get(nom, "1" if defaut else "0").strip().lower() in {"1", "true", "oui", "yes"}


@dataclass
class Parametres:
    database_url: str = "sqlite:///decensio.db"
    secret: str = "secret-de-developpement"
    api_key: str | None = None
    stocker_noms: bool = False
    # Décalage horaire local par rapport à UTC (Kinshasa : +1 ; Lubumbashi, Goma : +2).
    decalage_horaire: int = 1

    # Couverture : part de la population estimée déjà enregistrée.
    seuil_vert: float = 0.90
    seuil_orange: float = 0.70
    seuil_surcouverture: float = 1.15
    # En dessous de cette population estimée, la zone est jugée trop petite pour conclure.
    population_minimale: float = 50.0

    # Doublons : score de 0 à 1.
    seuil_doublon_probable: float = 0.85
    seuil_doublon_a_verifier: float = 0.70

    # Saisies suspectes.
    precision_gps_max_m: float = 50.0
    taille_menage_max: int = 25
    duree_min_entre_menages_s: float = 180.0
    menages_max_par_jour: int = 40
    heure_debut_travail: int = 6
    heure_fin_travail: int = 21
    rayon_empilement_m: float = 5.0
    empilement_min: int = 5

    extra: dict = field(default_factory=dict)

    @classmethod
    def depuis_environnement(cls) -> "Parametres":
        _charger_fichier_env()
        return cls(
            database_url=os.environ.get("DECENSIO_DATABASE_URL", cls.database_url),
            secret=os.environ.get("DECENSIO_SECRET", cls.secret),
            api_key=os.environ.get("DECENSIO_API_KEY") or None,
            stocker_noms=_bool("DECENSIO_STOCKER_NOMS", False),
            decalage_horaire=int(os.environ.get("DECENSIO_DECALAGE_HORAIRE", cls.decalage_horaire)),
            seuil_vert=_float("DECENSIO_SEUIL_VERT", cls.seuil_vert),
            seuil_orange=_float("DECENSIO_SEUIL_ORANGE", cls.seuil_orange),
            seuil_surcouverture=_float("DECENSIO_SEUIL_SURCOUVERTURE", cls.seuil_surcouverture),
            population_minimale=_float("DECENSIO_POPULATION_MINIMALE", cls.population_minimale),
            seuil_doublon_probable=_float("DECENSIO_SEUIL_DOUBLON_PROBABLE", cls.seuil_doublon_probable),
            seuil_doublon_a_verifier=_float("DECENSIO_SEUIL_DOUBLON_A_VERIFIER", cls.seuil_doublon_a_verifier),
        )


_parametres: Parametres | None = None


def parametres() -> Parametres:
    global _parametres
    if _parametres is None:
        _parametres = Parametres.depuis_environnement()
    return _parametres


def definir_parametres(p: Parametres) -> None:
    """Remplace les paramètres globaux (utile pour les tests)."""
    global _parametres
    _parametres = p
