"""Modèle de données de Decensio.

Le schéma reste compatible SQLite (développement, tests) et PostgreSQL (Supabase, production).
Les géométries sont stockées en GeoJSON ; les calculs spatiaux se font avec Shapely.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def maintenant() -> datetime:
    return datetime.now(timezone.utc)


class Zone(Base):
    """Zone géographique : province, commune, zone de santé, aire de santé, quartier…"""

    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    nom: Mapped[str] = mapped_column(String(200))
    niveau: Mapped[str] = mapped_column(String(40), index=True, default="quartier")
    code_parent: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    geometrie: Mapped[str] = mapped_column(Text)  # GeoJSON (EPSG:4326)
    superficie_km2: Mapped[float | None] = mapped_column(Float, nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)

    estimations: Mapped[list["EstimationPopulation"]] = relationship(
        back_populates="zone", cascade="all, delete-orphan"
    )


class EstimationPopulation(Base):
    """Population attendue dans une zone, selon une source (GRID3, RGPH-2, projection INS…)."""

    __tablename__ = "estimations_population"
    __table_args__ = (UniqueConstraint("zone_id", "source", name="uq_estimation_zone_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(80))
    population: Mapped[float] = mapped_column(Float)
    borne_basse: Mapped[float | None] = mapped_column(Float, nullable=True)
    borne_haute: Mapped[float | None] = mapped_column(Float, nullable=True)
    date_reference: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)

    zone: Mapped[Zone] = relationship(back_populates="estimations")


class LotImport(Base):
    """Un lot de données reçu : export CSPro, fichier d'enrôlement, synchronisation d'une tablette…"""

    __tablename__ = "lots_import"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(80))
    fichier: Mapped[str | None] = mapped_column(String(300), nullable=True)
    nb_menages: Mapped[int] = mapped_column(Integer, default=0)
    nb_personnes: Mapped[int] = mapped_column(Integer, default=0)
    importe_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)


class Menage(Base):
    __tablename__ = "menages"

    id: Mapped[int] = mapped_column(primary_key=True)
    identifiant_externe: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    lot_id: Mapped[int | None] = mapped_column(ForeignKey("lots_import.id"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    appareil_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    collecte_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lat: Mapped[float | None] = mapped_column(Float, nullable=True)
    lon: Mapped[float | None] = mapped_column(Float, nullable=True)
    precision_gps_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    zone_assignee_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True, index=True)
    taille_declaree: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)

    personnes: Mapped[list["Personne"]] = relationship(
        back_populates="menage", cascade="all, delete-orphan", order_by="Personne.rang"
    )
    zone: Mapped[Zone | None] = relationship()


class Personne(Base):
    __tablename__ = "personnes"

    id: Mapped[int] = mapped_column(primary_key=True)
    menage_id: Mapped[int] = mapped_column(ForeignKey("menages.id", ondelete="CASCADE"), index=True)
    identifiant_externe: Mapped[str | None] = mapped_column(String(120), nullable=True)
    rang: Mapped[int] = mapped_column(Integer, default=1)
    # Nom en clair : seulement si DECENSIO_STOCKER_NOMS=1.
    nom_affiche: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # Clés phonétiques des éléments du nom (triées, séparées par des espaces).
    cles_phonetiques: Mapped[str] = mapped_column(String(300), default="")
    # Empreintes HMAC des éléments du nom normalisés (pour les correspondances exactes).
    jetons_nom: Mapped[str] = mapped_column(Text, default="")
    sexe: Mapped[str | None] = mapped_column(String(1), nullable=True)
    date_naissance: Mapped[date | None] = mapped_column(Date, nullable=True)
    annee_naissance: Mapped[int | None] = mapped_column(Integer, nullable=True)
    age: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lien: Mapped[str | None] = mapped_column(String(40), nullable=True)
    nin_empreinte: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # Groupe de doublons : toutes les fiches d'une même personne partagent le même numéro.
    groupe_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    menage: Mapped[Menage] = relationship(back_populates="personnes")
    cles: Mapped[list["CleNom"]] = relationship(cascade="all, delete-orphan")


class CleNom(Base):
    """Une clé phonétique par élément du nom : sert à retrouver vite les fiches à comparer."""

    __tablename__ = "cles_noms"
    __table_args__ = (Index("ix_cle_nom_prefixe", "prefixe"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    personne_id: Mapped[int] = mapped_column(ForeignKey("personnes.id", ondelete="CASCADE"), index=True)
    cle: Mapped[str] = mapped_column(String(80))
    prefixe: Mapped[str] = mapped_column(String(4))


class PaireDoublon(Base):
    """Deux fiches qui désignent probablement la même personne."""

    __tablename__ = "paires_doublons"
    __table_args__ = (
        UniqueConstraint("personne_a_id", "personne_b_id", name="uq_paire"),
        Index("ix_paire_statut", "statut", "niveau"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    personne_a_id: Mapped[int] = mapped_column(ForeignKey("personnes.id", ondelete="CASCADE"), index=True)
    personne_b_id: Mapped[int] = mapped_column(ForeignKey("personnes.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    niveau: Mapped[str] = mapped_column(String(20))  # probable | a_verifier
    details: Mapped[str] = mapped_column(Text, default="{}")  # JSON : contribution de chaque critère
    statut: Mapped[str] = mapped_column(String(20), default="en_attente")  # en_attente | confirme | rejete
    decide_par: Mapped[str | None] = mapped_column(String(120), nullable=True)
    decide_le: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)

    personne_a: Mapped[Personne] = relationship(foreign_keys=[personne_a_id])
    personne_b: Mapped[Personne] = relationship(foreign_keys=[personne_b_id])


class Anomalie(Base):
    """Saisie suspecte repérée automatiquement."""

    __tablename__ = "anomalies"

    id: Mapped[int] = mapped_column(primary_key=True)
    type: Mapped[str] = mapped_column(String(60), index=True)
    gravite: Mapped[str] = mapped_column(String(10))  # haute | moyenne | basse
    cible: Mapped[str] = mapped_column(String(10))  # menage | personne | agent
    menage_id: Mapped[int | None] = mapped_column(ForeignKey("menages.id", ondelete="CASCADE"), nullable=True)
    personne_id: Mapped[int | None] = mapped_column(ForeignKey("personnes.id", ondelete="CASCADE"), nullable=True)
    agent_id: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    zone_id: Mapped[int | None] = mapped_column(ForeignKey("zones.id"), nullable=True)
    message: Mapped[str] = mapped_column(Text)
    valeur: Mapped[float | None] = mapped_column(Float, nullable=True)
    statut: Mapped[str] = mapped_column(String(20), default="ouverte")  # ouverte | justifiee | corrigee
    cree_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)


class CouvertureZone(Base):
    """Résultat du dernier calcul de couverture pour une zone."""

    __tablename__ = "couverture_zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id", ondelete="CASCADE"), unique=True)
    source_estimation: Mapped[str | None] = mapped_column(String(80), nullable=True)
    population_estimee: Mapped[float | None] = mapped_column(Float, nullable=True)
    menages: Mapped[int] = mapped_column(Integer, default=0)
    personnes_enregistrees: Mapped[int] = mapped_column(Integer, default=0)
    personnes_uniques: Mapped[int] = mapped_column(Integer, default=0)
    taux: Mapped[float | None] = mapped_column(Float, nullable=True)
    statut: Mapped[str] = mapped_column(String(20))
    calcule_le: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant)

    zone: Mapped[Zone] = relationship()


class JournalAudit(Base):
    """Trace de chaque action d'écriture : qui, quoi, quand (exigence de protection des données)."""

    __tablename__ = "journal_audit"

    id: Mapped[int] = mapped_column(primary_key=True)
    horodatage: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=maintenant, index=True)
    acteur: Mapped[str] = mapped_column(String(120))
    action: Mapped[str] = mapped_column(String(60))
    objet: Mapped[str | None] = mapped_column(String(120), nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
