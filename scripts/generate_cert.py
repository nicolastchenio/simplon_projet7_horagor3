"""
scripts/generate_cert.py
=========================
Génère un certificat TLS **auto-signé** pour la démo HorRAGor (Phase 7.3).

Ce script crée deux fichiers dans ``certs/`` :

* ``key.pem``  : la clé privée (SECRÈTE, ne jamais versionner) ;
* ``cert.pem`` : le certificat public auto-signé.

Ces fichiers permettent à Uvicorn de servir l'API Intelligence en **HTTPS**,
afin de chiffrer la communication Streamlit → API (tokens JWT, messages).

.. warning::
   Un certificat **auto-signé** convient uniquement pour la démo/formation.
   En production réelle, on utiliserait un certificat émis par une autorité
   de confiance (ex. Let's Encrypt).

Usage
-----
.. code-block:: bash

   python scripts/generate_cert.py
"""

from __future__ import annotations

import datetime
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

# Dossier de sortie des certificats (créé s'il n'existe pas)
CERTS_DIR = Path(__file__).resolve().parent.parent / "certs"


def generate_self_signed_cert() -> None:
    """Génère une clé privée RSA et un certificat X.509 auto-signé.

    La fonction écrit deux fichiers PEM dans le dossier ``certs/`` :
    ``key.pem`` (clé privée) et ``cert.pem`` (certificat public).

    :returns: ``None``. Les fichiers sont écrits sur le disque.
    """
    # ── 1. Créer le dossier de sortie ──
    CERTS_DIR.mkdir(parents=True, exist_ok=True)

    # ── 2. Générer la clé privée RSA (2048 bits = standard sécurisé) ──
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )

    # ── 3. Décrire l'identité du certificat ──
    # Common Name (CN) = nom du service tel qu'il apparaît sur le réseau Docker.
    # "horragor-ia" est le nom du conteneur Intelligence API.
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "HorRAGor Demo"),
        x509.NameAttribute(NameOID.COMMON_NAME, "horragor-ia"),
    ])

    # ── 4. Construire le certificat ──
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)               # Auto-signé : émetteur = sujet
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.now(datetime.UTC))
        .not_valid_after(
            # Validité : 1 an (largement suffisant pour une démo)
            datetime.datetime.now(datetime.UTC)
            + datetime.timedelta(days=365)
        )
        # ── 5. Noms alternatifs (SAN) : indispensables pour la validation ──
        # On autorise plusieurs noms possibles pour joindre l'API :
        # - horragor-ia  : nom du conteneur (réseau Docker interne)
        # - localhost    : accès local en dev
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("horragor-ia"),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        # ── 6. Signer le certificat avec la clé privée (SHA-256) ──
        .sign(private_key, hashes.SHA256())
    )

    # ── 7. Écrire la clé privée sur disque (key.pem) ──
    key_path = CERTS_DIR / "key.pem"
    with open(key_path, "wb") as f:
        f.write(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

    # ── 8. Écrire le certificat public sur disque (cert.pem) ──
    cert_path = CERTS_DIR / "cert.pem"
    with open(cert_path, "wb") as f:
        f.write(certificate.public_bytes(serialization.Encoding.PEM))

    print("✅ Certificat auto-signé généré avec succès !")
    print(f"   🔒 Clé privée   : {key_path}")
    print(f"   📜 Certificat   : {cert_path}")


if __name__ == "__main__":
    generate_self_signed_cert()