import json
from datetime import timezone

import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import box

from decensio.ingest import lire_csv_texte, menages_depuis_json
from decensio.population import somme_par_zone


def test_csv_style_cspro_reconnu():
    texte = (
        "HH_ID,Enumerator,Start,GPS_Latitude,GPS_Longitude,Line_Number,Last_Name,Middle_Name,First_Name,Sex,DOB,Age,Relationship\n"
        "H1,E7,15/12/2026 09:30,-4.40,15.37,1,Ilunga,Kasongo,Jean,1,02/05/1990,36,1\n"
        "H1,E7,15/12/2026 09:30,-4.40,15.37,2,Ilunga,,Marie,2,,8,3\n"
    )
    menages = lire_csv_texte(texte)
    assert len(menages) == 1
    m = menages[0]
    assert m.identifiant == "H1" and m.agent_id == "E7" and m.lat == -4.40
    # 09:30 à Kinshasa (UTC+1) = 08:30 UTC
    assert m.collecte_le.astimezone(timezone.utc).hour == 8
    assert [p.sexe for p in m.membres] == ["M", "F"]
    assert m.membres[0].lien == "chef" and m.membres[1].lien == "enfant"
    assert m.membres[0].date_naissance.isoformat() == "1990-05-02"


def test_csv_point_virgule_et_decimales_francaises():
    texte = "menage_id;latitude;longitude;nom;sexe;age\nM1;-4,40;15,37;Kabasele;F;30\n"
    m = lire_csv_texte(texte)[0]
    assert m.lat == -4.40 and m.lon == 15.37 and m.membres[0].age == 30


def test_json_de_synchronisation():
    m = menages_depuis_json({"menages": [{"identifiant": "T-1", "lat": -4.4, "lon": 15.3, "membres": [{"nom": "Mbala", "sexe": "M", "age": 40}]}]})
    assert m[0].identifiant == "T-1" and m[0].membres[0].rang == 1


def test_somme_zonale(tmp_path):
    chemin = tmp_path / "g.tif"
    donnees = np.ones((10, 10), dtype="float32") * 2
    donnees[0, 0] = -99999  # cellule sans donnée
    with rasterio.open(chemin, "w", driver="GTiff", height=10, width=10, count=1, dtype="float32",
                       crs="EPSG:4326", transform=from_origin(0, 10, 1, 1), nodata=-99999) as dst:
        dst.write(donnees, 1)
    r = somme_par_zone(chemin, {"gauche": box(0, 0, 5, 10), "tout": box(0, 0, 10, 10), "dehors": box(50, 50, 60, 60)})
    assert r["gauche"].population == 2 * 50 - 2
    assert r["tout"].population == 2 * 100 - 2
    assert r["dehors"].population == 0
