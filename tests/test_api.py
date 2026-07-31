"""API : authentification, validation des chemins, identifiants réels (constats M7 et Mod6)."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.core.models import Act, Person

client = TestClient(app)


# ------------------------------------------------------------------ M7 : sécurité
def test_cors_ne_reflechit_pas_une_origine_arbitraire():
    """M7 : allow_origins=["*"] avec allow_credentials=True est supprimé."""
    response = client.get("/api/stats", headers={"Origin": "https://evil.example"})

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") != "https://evil.example"


@pytest.mark.parametrize(
    "endpoint, payload",
    [
        ("/api/pipeline/process", {"image_path": "pyproject.toml"}),
        ("/api/import/gedcom", {"gedcom_path": "C:/Windows/win.ini"}),
    ],
)
def test_endpoints_mutants_refuses_sans_jeton(endpoint, payload):
    """M7 : sans CERTUS_API_TOKEN, les endpoints qui écrivent sont désactivés."""
    assert client.post(endpoint, json=payload).status_code == 503


def test_jeton_invalide_refuse(api_token):
    response = client.post(
        "/api/pipeline/process",
        json={"image_path": "pyproject.toml"},
        headers={"Authorization": "Bearer mauvais-jeton"},
    )
    assert response.status_code == 403


def test_chemin_hors_racines_autorisees_refuse(api_token):
    """M7 : un chemin arbitraire n'est plus accepté (il renvoyait 200 et écrivait en base)."""
    response = client.post(
        "/api/pipeline/process",
        json={"image_path": "../../../Windows/System32/drivers/etc/hosts"},
        headers=api_token,
    )
    assert response.status_code == 403


def test_extension_non_autorisee_refusee(api_token):
    response = client.post(
        "/api/pipeline/process", json={"image_path": "pyproject.toml"}, headers=api_token
    )
    assert response.status_code == 400


def test_aucune_fuite_de_chemin_absolu(api_token):
    """M7 : les messages d'erreur ne divulguent plus l'arborescence du serveur."""
    responses = [
        client.post(
            "/api/pipeline/process", json={"image_path": "C:/Windows/win.ini"}, headers=api_token
        ),
        client.post(
            "/api/import/gedcom", json={"gedcom_path": "index.html"}, headers=api_token
        ),
    ]
    for response in responses:
        body = response.text
        assert "C:" + chr(92) not in body
        assert "D:" + chr(92) not in body
        assert "C:/" not in body


def test_import_gedcom_avec_jeton_et_chemin_valide(api_token, tmp_path, monkeypatch):
    """M7 : le chemin autorisé passe, et l'import fonctionne toujours."""
    sample = tmp_path / "fonds.ged"
    sample.write_text(
        "0 HEAD\n0 @I1@ INDI\n1 NAME Jean /VERGNE/\n2 GIVN Jean\n2 SURN VERGNE\n0 TRLR\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CERTUS_ALLOWED_DIRS", str(tmp_path))

    response = client.post(
        "/api/import/gedcom", json={"gedcom_path": str(sample)}, headers=api_token
    )

    assert response.status_code == 200
    assert response.json()["imported_count"] == 1


# --------------------------------------------------------- Mod6 : identifiants réels
def test_acts_recent_expose_les_cles_primaires():
    response = client.get("/api/acts/recent?limit=10")

    assert response.status_code == 200
    ids = [a["id"] for a in response.json()]
    assert ids and all(isinstance(i, int) and i > 0 for i in ids)
    assert len(set(ids)) == len(ids)


def test_detail_acte_par_cle_primaire_et_404():
    """Mod6 : l'acte est retrouvé par sa clé primaire, non par sa position dans la liste."""
    act_id = client.get("/api/acts/recent?limit=1").json()[0]["id"]

    detail = client.get(f"/api/acts/{act_id}")
    assert detail.status_code == 200
    assert detail.json()["id"] == act_id
    # M6 : l'état civil traverse la chaîne jusqu'à l'API.
    assert any(p.get("birth_date") for p in detail.json()["persons"])

    assert client.get("/api/acts/999999").status_code == 404


def test_pagination_bornee():
    assert client.get("/api/acts/recent?limit=0").status_code == 400
    assert client.get("/api/acts/recent?offset=-1").status_code == 400


# ------------------------------------------------------------------ lecture
def test_tree_et_exports():
    tree = client.get("/api/tree")
    assert tree.status_code == 200
    assert "nodes" in tree.json() and "edges" in tree.json()

    for endpoint in ("/api/export/json", "/api/export/mermaid", "/api/export/gedcom"):
        assert client.get(endpoint).status_code == 200

    gedcom = client.get("/api/export/gedcom")
    assert "0 HEAD" in gedcom.text and "0 TRLR" in gedcom.text


def test_stats_sans_valeur_inventee():
    """M3 : plus de score de repli à 0.90 ; le nombre d'actes simulés est exposé."""
    body = client.get("/api/stats").json()

    assert body["total_acts"] > 0
    assert body["simulated_acts"] == 0
    assert body["confidence_average"] == 1.0


def test_recherche_multi_sources_sans_fabrication():
    """M3 : sans autorisation de simulation, la recherche ne renvoie aucun acte inventé."""
    body = client.post("/api/search", json={"last_name": "VERGNE"}).json()

    assert body["simulated_acts"] == 0


def test_recherche_refuse_un_champ_inconnu():
    """Mod4 : surname= au lieu de last_name= est désormais une erreur de validation."""
    assert client.post("/api/search", json={"surname": "VERGNE"}).status_code == 422


def test_websocket_progress():
    with client.websocket_connect("/ws/progress") as websocket:
        websocket.send_text("ping")


# ------------------------------------------------------------------ sous-arbres (zoom)
def test_tree_sans_person_id_retourne_arbre_complet():
    """Comportement inchangé : sans person_id, /api/tree renvoie tout (rétrocompatible)."""
    full = client.get("/api/tree").json()
    assert set(full["nodes"]) >= {"I1", "I2", "I3", "I4"}


def test_tree_avec_person_id_retourne_un_sous_ensemble():
    """Centré sur l'enfant I1 en ne remontant que d'un niveau : les deux parents, pas plus."""
    body = client.get("/api/tree", params={"person_id": "I1", "up": 1, "down": 0}).json()
    assert set(body["nodes"]) == {"I1", "I2", "I3"}
    for edge in body["edges"]:
        assert edge["source_id"] in body["nodes"]
        assert edge["target_id"] in body["nodes"]


def test_tree_person_id_inconnu_404():
    response = client.get("/api/tree", params={"person_id": "N_EXISTE_PAS"})
    assert response.status_code == 404


def test_export_mermaid_avec_person_id_est_restreint():
    full = client.get("/api/export/mermaid").json()["mermaid"]
    subtree = client.get(
        "/api/export/mermaid", params={"person_id": "I1", "up": 0, "down": 0}
    ).json()["mermaid"]
    # Le sous-arbre à profondeur nulle ne contient qu'un seul nœud : sa syntaxe est
    # nécessairement plus courte que le diagramme complet (4 individus dans la fixture).
    assert len(subtree) < len(full)
    assert "graph BT" in subtree


def test_export_mermaid_person_id_inconnu_404():
    response = client.get("/api/export/mermaid", params={"person_id": "N_EXISTE_PAS"})
    assert response.status_code == 404


def test_pipeline_process_avec_ocr_mocke(api_token, tmp_path, monkeypatch):
    """Le pipeline complet fonctionne quand un moteur OCR est fourni."""
    image = tmp_path / "archive.jpg"
    image.write_bytes(b"dummy")
    monkeypatch.setenv("CERTUS_ALLOWED_DIRS", str(tmp_path))
    monkeypatch.setattr(
        "src.ocr.engine.HTREngine.extract_text", lambda self, path: "Texte brut"
    )
    monkeypatch.setattr(
        "src.parser.llm.LLMActParser.parse",
        lambda self, text: Act(
            act_type="naissance",
            date="1850-01-01",
            confidence_score=0.98,
            persons=[Person(first_name="Jean", last_name="VERGNE", role="enfant")],
        ),
    )

    response = client.post(
        "/api/pipeline/process", json={"image_path": str(image)}, headers=api_token
    )

    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert response.json()["act_id"] > 0
    assert response.json()["is_simulated"] is False
