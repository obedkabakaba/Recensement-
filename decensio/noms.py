"""Normalisation des noms et clés phonétiques adaptées aux noms congolais.

Un même nom s'écrit souvent de plusieurs façons d'un agent à l'autre :
Tshibangu / Tchibangu / Chibangu, Ilunga / Ilounga, Kasongo / Kassongo,
Kalonji / Kalondji, Mwamba / Mouamba, Kabasele / Kabasélé / Kabaselle…
La clé phonétique ramène ces variantes à une même forme pour comparer les noms
sans dépendre de l'orthographe.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata

# Mots qui ne servent pas à identifier une personne.
MOTS_VIDES = {"de", "du", "la", "le", "wa", "ya", "na", "mme", "mr", "m", "mlle", "papa", "maman", "mama"}

_REGLES: list[tuple[str, str]] = [
    # Graphies françaises du son « ou ».
    (r"ou", "u"),
    # Son « tch » / « ch » : Tshibangu, Tchibangu, Chibangu → cibangu.
    (r"tsh|tch|tsch|sh|ch", "c"),
    # « dj » → « j » : Kalondji → kalonji.
    (r"dj", "j"),
    (r"ph", "f"),
    (r"qu|ck|q", "k"),
    # « c » dur devant a, o, u → k (après la règle « ch »).
    (r"c(?=[aou])", "k"),
    (r"gu(?=[ei])", "g"),
    # « u » devant une voyelle se prononce « w » : muamba → mwamba.
    (r"(?<=[bcdfgjklmnpstvz])u(?=[aeio])", "w"),
    # « y » entre voyelles ou en fin de mot → i : Mbuyie → mbuii → mbui.
    (r"y", "i"),
    (r"ie$", "i"),
    # « h » muet (hors combinaisons déjà traitées).
    (r"h", ""),
    (r"ck", "k"),
    # « s » final muet des prénoms français : Jacques, Georges, Charles.
    (r"(?<=[a-z]{3})s$", ""),
    # « e » final muet.
    (r"(?<=[a-z]{3})e$", ""),
]
_REGLES_COMPILEES = [(re.compile(m), r) for m, r in _REGLES]


def sans_accents(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))


def normaliser(texte: str | None) -> str:
    """Minuscules, sans accents, lettres et espaces uniquement."""
    if not texte:
        return ""
    texte = sans_accents(texte).lower()
    texte = re.sub(r"[^a-z\s'-]", " ", texte)
    texte = re.sub(r"[\s'-]+", " ", texte)
    return texte.strip()


def elements_du_nom(*parties: str | None) -> list[str]:
    """Découpe nom, postnom et prénom en éléments utiles (« Kabila Kabange Joseph » → 3 éléments)."""
    elements: list[str] = []
    for partie in parties:
        for mot in normaliser(partie).split():
            if len(mot) >= 2 and mot not in MOTS_VIDES:
                elements.append(mot)
    return elements


def cle_phonetique(mot: str) -> str:
    """Clé phonétique d'un élément du nom."""
    cle = normaliser(mot).replace(" ", "")
    for motif, remplacement in _REGLES_COMPILEES:
        cle = motif.sub(remplacement, cle)
    # Lettres doublées : Kassongo → kasongo, Kabaselle → kabasele.
    cle = re.sub(r"(.)\1+", r"\1", cle)
    return cle


def cles_phonetiques(*parties: str | None) -> list[str]:
    return sorted({cle_phonetique(e) for e in elements_du_nom(*parties) if cle_phonetique(e)})


def empreinte(valeur: str, secret: str) -> str:
    """Empreinte HMAC-SHA256 tronquée : permet de comparer sans révéler la valeur."""
    return hmac.new(secret.encode("utf-8"), valeur.encode("utf-8"), hashlib.sha256).hexdigest()[:32]


def jetons_nom(secret: str, *parties: str | None) -> list[str]:
    return sorted({empreinte(e, secret) for e in elements_du_nom(*parties)})


def empreinte_nin(nin: str | None, secret: str) -> str | None:
    """Empreinte du numéro d'identification national (NIN) : jamais stocké en clair."""
    if not nin:
        return None
    nin_net = re.sub(r"[^0-9A-Za-z]", "", nin).upper()
    return empreinte("NIN:" + nin_net, secret) if nin_net else None
