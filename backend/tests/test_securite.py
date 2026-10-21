"""Filtres de sécurité (US130) : en-têtes défensifs, contrôle d'origine CSRF et validation d'entrée."""

from tests.conftest import MOT_DE_PASSE, creer_utilisateur


class TestEnTetesSecurite:
    def test_ajoute_les_entetes_defensifs(self, client):
        entetes = client.get("/health").headers
        assert entetes["x-content-type-options"] == "nosniff"
        assert entetes["x-frame-options"] == "DENY"
        assert entetes["referrer-policy"] == "no-referrer"
        assert "geolocation=()" in entetes["permissions-policy"]
        csp = entetes["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "frame-ancestors 'none'" in csp
        assert "object-src" not in csp  # hérité de default-src 'none'

    def test_entetes_presents_meme_sur_une_erreur(self, client):
        reponse = client.get("/api/v1/users")
        assert reponse.status_code == 401
        assert reponse.headers["x-content-type-options"] == "nosniff"
        assert "content-security-policy" in reponse.headers

    def test_hsts_seulement_en_https(self, client):
        assert "strict-transport-security" not in client.get("/health").headers


class TestFiltreCsrf:
    def test_refuse_une_origine_inconnue_sur_une_ecriture(self, client):
        reponse = client.post("/api/v1/auth/login", json={}, headers={"Origin": "https://attaquant.example"})
        assert reponse.status_code == 403
        assert reponse.json()["detail"] == "Origine non autorisée."

    def test_refuse_une_requete_intersite_sans_origine(self, client):
        reponse = client.post("/api/v1/auth/login", json={}, headers={"Sec-Fetch-Site": "cross-site"})
        assert reponse.status_code == 403
        assert reponse.json()["detail"] == "Requête intersite refusée."

    def test_accepte_l_origine_du_frontend(self, client, db):
        utilisateur = creer_utilisateur(db)
        reponse = client.post(
            "/api/v1/auth/login",
            headers={"Origin": "http://localhost:3000", "Sec-Fetch-Site": "same-site"},
            json={"email": utilisateur.email, "mot_de_passe": MOT_DE_PASSE},
        )
        assert reponse.status_code == 200

    def test_laisse_passer_un_client_non_navigateur(self, client, db):
        utilisateur = creer_utilisateur(db)
        reponse = client.post(
            "/api/v1/auth/login",
            json={"email": utilisateur.email, "mot_de_passe": MOT_DE_PASSE},
        )
        assert reponse.status_code == 200

    def test_ne_filtre_pas_les_lectures(self, client):
        reponse = client.get("/api/v1/formules", headers={"Origin": "https://attaquant.example"})
        assert reponse.status_code == 200


class TestValidationEtInjectionSql:
    def test_recherche_trop_longue_refusee(self, client, admin_entete):
        reponse = client.get("/api/v1/users", headers=admin_entete, params={"search": "a" * 101})
        assert reponse.status_code == 422

    def test_recherche_traitee_comme_une_valeur_liee(self, client, db, admin_entete):
        creer_utilisateur(db, email="cible@exemple.com", nom="RABE")
        creer_utilisateur(db, email="autre@exemple.com", nom="RAKOTO")

        reponse = client.get("/api/v1/users", headers=admin_entete, params={"search": "' OR 1=1 --"})
        assert reponse.status_code == 200
        assert reponse.json()["total"] == 0

        # La table n'a pas été altérée ni vidée par la tentative d'injection.
        assert client.get("/api/v1/users", headers=admin_entete).json()["total"] == 3

    def test_joker_like_recherche_litteralement(self, client, db, admin_entete):
        creer_utilisateur(db, email="cible@exemple.com", nom="RABE")
        assert client.get("/api/v1/users", headers=admin_entete, params={"search": "%"}).json()["total"] == 0
