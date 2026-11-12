from fastapi.testclient import TestClient

from decensio.api.app import app
from decensio.config import parametres


def _menage(ident, nom="Tshibangu", lat=-4.401):
    return {
        "identifiant": ident, "agent_id": "AG1", "collecte_le": "2026-09-01T10:00:00", "lat": lat, "lon": 15.37,
        "membres": [
            {"nom": nom, "postnom": "Mukendi", "prenom": "Jean", "sexe": "M", "date_naissance": "1985-03-12", "lien": "chef"},
            {"nom": "Ilunga", "postnom": "Kasongo", "prenom": "Marie", "sexe": "F", "date_naissance": "1988-07-01", "lien": "conjoint"},
        ],
    }


def test_sync_renvoie_une_alerte_de_doublon(params):
    with TestClient(app) as c:
        assert c.get("/api/sante").json()["statut"] == "ok"
        r1 = c.post("/api/sync", json={"menages": [_menage("A-1")]}).json()
        assert r1["alertes_doublons"] == []
        # Le même ménage, recensé par un autre agent avec une autre orthographe.
        r2 = c.post("/api/sync", json={"menages": [_menage("B-7", nom="Tchibangu", lat=-4.4011)]}).json()
        assert len(r2["alertes_doublons"]) == 2
        assert {a["correspond_a_menage"] for a in r2["alertes_doublons"]} == {"A-1"}
        assert all(a["niveau"] == "probable" for a in r2["alertes_doublons"])

        doublons = c.get("/api/doublons").json()
        assert doublons["total"] == 2
        assert doublons["paires"][0]["a"]["nom"] is None  # noms non conservés par défaut

        pid = doublons["paires"][0]["id"]
        assert c.post(f"/api/doublons/{pid}/decision", json={"decision": "rejete"}).json()["statut"] == "rejete"
        assert c.get("/api/doublons?statut=rejete").json()["total"] == 1
        assert any(j["action"] == "decision_doublon" for j in c.get("/api/journal").json())


def test_cle_api_obligatoire_si_definie(params):
    parametres().api_key = "secrete"
    try:
        with TestClient(app) as c:
            assert c.post("/api/recalcul").status_code == 401
            assert c.post("/api/recalcul", headers={"X-Cle-API": "secrete"}).status_code == 200
            assert c.get("/api/resume").status_code == 200  # la lecture reste ouverte
    finally:
        parametres().api_key = None


def test_tableau_de_bord_servi(params):
    with TestClient(app) as c:
        r = c.get("/")
        assert r.status_code == 200 and "Decens" in r.text
        assert c.get("/static/app.js").status_code == 200
