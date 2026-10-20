"""Authentification : POST /auth/login, /auth/register, /auth/forgot-password, /auth/reset-password.

Sécurité du jeton de session (JWT HS256) : usage « acces » vs « reinitialisation », expiration,
signature, et révocation d'une session quand le compte n'est plus actif.
"""

from datetime import UTC, datetime, timedelta

import bcrypt
from jose import jwt as jose_jwt
from sqlalchemy import select

from app.core.config import get_settings
from app.core.security import USAGE_ACCES, creer_jeton_acces, creer_jeton_reinitialisation
from app.models import Abonnement, Role, StatutAbonnement, StatutUtilisateur, Utilisateur
from tests.conftest import MOT_DE_PASSE, creer_utilisateur

RESSOURCE_PROTEGEE = "/api/v1/users/me"

INSCRIPTION = {
    "prenom": "Rova",
    "nom": "RAKOTO",
    "email": "Rova@Exemple.com",
    "mot_de_passe": "Langue2026",
    "date_naissance": "2000-05-01",
    "langues": ["en", "zh"],
    "id_formule": 2,
}


def connexion(client, email="rova@exemple.com", mot_de_passe=MOT_DE_PASSE):
    return client.post("/api/v1/auth/login", json={"email": email, "mot_de_passe": mot_de_passe})


class TestConnexion:
    def test_renvoie_le_jeton_et_l_utilisateur_sans_mot_de_passe(self, client, db):
        creer_utilisateur(db)
        reponse = connexion(client, email=" ROVA@exemple.com ")

        assert reponse.status_code == 200
        corps = reponse.json()
        assert corps["token_type"] == "bearer" and corps["access_token"]
        assert corps["utilisateur"]["email"] == "rova@exemple.com"
        assert corps["utilisateur"]["role"] == "APPRENANT"
        assert corps["utilisateur"]["statut"] == "ACTIF"
        assert "mot_de_passe" not in corps["utilisateur"]

    def test_meme_refus_401_pour_un_mauvais_mot_de_passe_et_un_email_inconnu(self, client, db):
        creer_utilisateur(db)
        assert connexion(client, mot_de_passe="Mauvais2026").status_code == 401
        assert connexion(client, email="inconnu@exemple.com").status_code == 401

    def test_refuse_un_compte_inactif_ou_suspendu_avec_403(self, client, db):
        creer_utilisateur(db, email="inactif@exemple.com", statut=StatutUtilisateur.INACTIF)
        creer_utilisateur(db, email="suspendu@exemple.com", statut=StatutUtilisateur.SUSPENDU)
        assert connexion(client, email="inactif@exemple.com").status_code == 403
        assert connexion(client, email="suspendu@exemple.com").status_code == 403


class TestInscription:
    def test_cree_l_apprenant_ses_langues_et_son_abonnement(self, client, db):
        reponse = client.post("/api/v1/auth/register", json=INSCRIPTION)

        assert reponse.status_code == 201, reponse.text
        corps = reponse.json()
        assert corps["email"] == "rova@exemple.com"
        assert corps["role"] == "APPRENANT"
        assert corps["date_naissance"] == "2000-05-01"
        assert {"pays", "ville", "objectif"} <= corps.keys()
        assert "mot_de_passe" not in corps

        utilisateur = db.scalar(select(Utilisateur).where(Utilisateur.email == "rova@exemple.com"))
        assert sorted(langue.code for langue in utilisateur.apprenant.langues) == ["en", "zh"]
        abonnement = db.scalar(select(Abonnement).where(Abonnement.id_apprenant == utilisateur.id_user))
        assert abonnement.statut == StatutAbonnement.ACTIF
        assert abonnement.formule.libelle == "Luxe"
        assert (abonnement.quota_heures, abonnement.quota_ateliers) == (12, 3)
        # L'apprenant peut ensuite se connecter
        assert connexion(client).status_code == 200

    def test_refuse_un_email_deja_utilise_avec_409(self, client, db):
        creer_utilisateur(db)
        assert client.post("/api/v1/auth/register", json=INSCRIPTION).status_code == 409

    def test_refuse_une_formule_ou_une_langue_inconnue_avec_422(self, client):
        assert client.post("/api/v1/auth/register", json={**INSCRIPTION, "id_formule": 999}).status_code == 422
        reponse = client.post("/api/v1/auth/register", json={**INSCRIPTION, "langues": ["xx"]})
        assert reponse.status_code == 422
        assert "xx" in reponse.json()["detail"]

    def test_applique_les_regles_du_frontend(self, client):
        cas = [
            ({"mot_de_passe": "court1A"}, "au moins 8 caractères"),
            ({"mot_de_passe": "toutminuscule1"}, "une majuscule et une minuscule"),
            ({"mot_de_passe": "SansChiffre"}, "un chiffre"),
            ({"prenom": "Rova2"}, "Le prénom ne doit contenir que des lettres"),
            ({"email": "pas-un-email"}, "Adresse e-mail invalide."),
            ({"date_naissance": "2999-01-01"}, "dans le futur"),
            ({"langues": []}, None),
        ]
        for champs, message in cas:
            reponse = client.post("/api/v1/auth/register", json={**INSCRIPTION, **champs})
            assert reponse.status_code == 422, champs
            if message:
                # Message affiché tel quel par le frontend (sans préfixe « Value error, »)
                assert message in reponse.json()["detail"][0]["msg"], champs


class TestMotDePasseOublie:
    def test_repond_204_que_le_compte_existe_ou_non(self, client, db, monkeypatch):
        envoyes = []
        monkeypatch.setattr("app.api.routes.auth.envoyer_lien_reinitialisation", lambda *args: envoyes.append(args))
        creer_utilisateur(db)

        assert client.post("/api/v1/auth/forgot-password", json={"email": "inconnu@exemple.com"}).status_code == 204
        assert client.post("/api/v1/auth/forgot-password", json={"email": "rova@exemple.com"}).status_code == 204
        assert [args[0] for args in envoyes] == ["rova@exemple.com"]

    def test_le_lien_change_le_mot_de_passe_une_seule_fois(self, client, db):
        utilisateur = creer_utilisateur(db)
        jeton = creer_jeton_reinitialisation(utilisateur.id_user, utilisateur.mot_de_passe)
        corps = {"token": jeton, "nouveau_mot_de_passe": "Nouveau2026"}

        assert client.post("/api/v1/auth/reset-password", json=corps).status_code == 204
        assert connexion(client, mot_de_passe="Nouveau2026").status_code == 200
        assert connexion(client).status_code == 401
        # Le même lien ne sert plus : il dépendait de l'ancien mot de passe
        assert client.post("/api/v1/auth/reset-password", json=corps).status_code == 400

    def test_refuse_un_jeton_invalide_ou_un_jeton_de_session(self, client, db):
        utilisateur = creer_utilisateur(db)
        for jeton in ("pas-un-jeton", creer_jeton_acces(utilisateur.id_user)):
            reponse = client.post(
                "/api/v1/auth/reset-password", json={"token": jeton, "nouveau_mot_de_passe": "Nouveau2026"}
            )
            assert reponse.status_code == 400

    def test_un_jeton_de_reinitialisation_n_ouvre_pas_de_session(self, client, db):
        utilisateur = creer_utilisateur(db, role=Role.APPRENANT)
        jeton = creer_jeton_reinitialisation(utilisateur.id_user, utilisateur.mot_de_passe)
        assert client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {jeton}"}).status_code == 401


def _en_tete(jeton: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jeton}"}


def _jeton_signe(id_user: int, cle: str, usage: str = USAGE_ACCES, minutes: int = 10) -> str:
    """Émet un jeton arbitraire (bonne ou mauvaise clé, usage quelconque) pour éprouver le serveur."""
    settings = get_settings()
    claims = {"sub": str(id_user), "usage": usage, "exp": datetime.now(UTC) + timedelta(minutes=minutes)}
    return jose_jwt.encode(claims, cle, settings.algorithm)


class TestSecuriteJeton:
    """Le JWT est le cœur de la session : chaque défense est testée isolément."""

    def test_le_jeton_de_connexion_ouvre_une_route_protegee(self, client, db):
        creer_utilisateur(db)
        jeton = connexion(client).json()["access_token"]

        reponse = client.get(RESSOURCE_PROTEGEE, headers=_en_tete(jeton))

        assert reponse.status_code == 200
        assert reponse.json()["email"] == "rova@exemple.com"

    def test_refuse_un_jeton_falsifie_ou_signe_d_une_autre_cle(self, client, db):
        utilisateur = creer_utilisateur(db)
        # Bonne structure, signature d'une autre clé : le serveur doit la rejeter
        for jeton in (
            _jeton_signe(utilisateur.id_user, "mauvaise-cle-secrete"),
            f"{connexion(client).json()['access_token'][:-2]}xx",  # dernier octet modifié
        ):
            assert client.get(RESSOURCE_PROTEGEE, headers=_en_tete(jeton)).status_code == 401

    def test_refuse_un_jeton_expire(self, client, db):
        utilisateur = creer_utilisateur(db)
        expire = _jeton_signe(utilisateur.id_user, get_settings().secret_key, minutes=-1)

        assert client.get(RESSOURCE_PROTEGEE, headers=_en_tete(expire)).status_code == 401

    def test_refuse_un_jeton_sans_usage_de_session(self, client, db):
        utilisateur = creer_utilisateur(db)
        reinitialisation = creer_jeton_reinitialisation(utilisateur.id_user, utilisateur.mot_de_passe)

        assert client.get(RESSOURCE_PROTEGEE, headers=_en_tete(reinitialisation)).status_code == 401

    def test_refuse_un_jeton_d_une_classe_inconnue(self, client, db):
        utilisateur = creer_utilisateur(db)
        etranger = jose_jwt.encode(
            {"sub": str(utilisateur.id_user), "exp": datetime.now(UTC) + timedelta(minutes=10)},
            get_settings().secret_key,
            get_settings().algorithm,
        )

        assert client.get(RESSOURCE_PROTEGEE, headers=_en_tete(etranger)).status_code == 401

    def test_revoque_une_session_quand_le_compte_est_desactive(self, client, db):
        """Un JWT encore valide ne doit plus rien ouvrir une fois le compte désactivé (révocation serveur)."""
        utilisateur = creer_utilisateur(db)
        jeton = connexion(client).json()["access_token"]
        assert client.get(RESSOURCE_PROTEGEE, headers=_en_tete(jeton)).status_code == 200

        utilisateur.statut = StatutUtilisateur.INACTIF
        db.commit()

        assert client.get(RESSOURCE_PROTEGEE, headers=_en_tete(jeton)).status_code == 401

    def test_refuse_une_connexion_sans_en_tete_authorization(self, client, db):
        creer_utilisateur(db)

        assert client.get(RESSOURCE_PROTEGEE).status_code == 401
        assert client.get(RESSOURCE_PROTEGEE, headers={"Authorization": "Banana"}).status_code == 401


class TestHachageMotDePasse:
    """Le mot de passe n'est jamais stocké en clair : uniquement un hachage bcrypt vérifiable."""

    def test_le_mot_de_passe_est_hache_en_bcrypt_et_retrouvable(self, client, db):
        client.post("/api/v1/auth/register", json=INSCRIPTION)
        utilisateur = db.scalar(select(Utilisateur).where(Utilisateur.email == "rova@exemple.com"))

        assert utilisateur.mot_de_passe != INSCRIPTION["mot_de_passe"]
        assert utilisateur.mot_de_passe.startswith("$2b$")
        assert bcrypt.checkpw(
            INSCRIPTION["mot_de_passe"].encode(), utilisateur.mot_de_passe.encode()
        )
