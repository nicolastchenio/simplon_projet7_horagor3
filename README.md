# Structure du projet

```
horragor-project/
├── data/                       # Données + script de génération de l'index vectoriel
│   └── faiss_index/            # Index vectoriel généré en Phase 1
│   │   ├── horror_index.faiss  # Index binaire FAISS (embeddings 768D)
│   │   └── metadata.pkl        # Métadonnées liées aux vecteurs (id_film, titre, année)
│   └── build_faiss_index.py    # Script one-shot : génère l'index FAISS depuis Supabase
├── data_api/                   # Micro-service FastAPI d'accès aux données (Phase 6)
│   ├── __init__.py             # Marqueur de package Python
│   ├── config.py               # Config logs (Phase 8.2)
│   ├── database.py             # Connexion PostgreSQL + wrapper de logging SQL (Phase 8.2)
│   ├── models.py               # Schémas Pydantic (requêtes/réponses de l'API Données)
│   ├── main.py                 # Point d'entrée FastAPI du service Données (port 8001)
│   ├── observability/          # Logging Loguru autonome du service Données (Phase 8.2)
│   │   ├── __init__.py         # Marqueur de package Python
│   │   └── logging_config.py   # Config Loguru (JSON, rotation, interception stdlib)
│   └── routers/                # Endpoints métiers (recherche, fiche film, similarité)
│       ├── __init__.py         # Marqueur de package Python
│       └── films.py            # Routes /films (recherche, fuzzy, détail, similarité pgvector)
├── docker                      # Dockerfiles des 3 services
│   ├── data_api.Dockerfile     # Image du service Données (port 8001)
│   ├── frontend.Dockerfile     # Image du frontend Streamlit (port 8501)
│   └── intelligence_api.Dockerfile  # Image du service Intelligence (port 8000, HTTPS)
├── grafana/                    # Provisioning Grafana (Phase 8.3)
│   └── provisioning/           # Auto-configuration au démarrage de Grafana
│       └── datasources/        # Datasource provisionnée automatiquement
│           └── datasource.yml  # Déclare Prometheus comme source de données par défaut
├── scripts                     # Scripts utilitaires ponctuels
│   ├── faiss_to_pgvector.py    # Copie les vecteurs FAISS existants vers la colonne pgvector
│   └── generate_cert.py        # Génère un certificat TLS auto-signé (Phase 7.3)
├── .streamlit/                 # Configuration Streamlit
│   └── config.toml             # Thème "Horror" (Phase 0.4)
├── observability/              # Logging Streamlit (Phase 8.2)
│   ├── __init__.py             # Marqueur de package Python
│   └── logging_config.py       # Config Loguru autonome du frontend Streamlit
├── src/                        # API Intelligence (LangGraph, RAG, narration)
│   ├── __init__.py             # Marqueur de package Python
│   ├── main.py                 # Serveur FastAPI (API Intelligence)
│   ├── config.py               # Config Ollama, clés API, chemins
│   │──api/                     # Endpoints d'authentification
│   │   ├── __init__.py         # Marqueur de package Python
│   │   └── auth.py  
│   │──observability/           # Logging Loguru + intégration Langfuse
│   │   ├── __init__.py         # Marqueur de package Python
│   │   ├── logging_config.py   # Config Loguru (JSON, rotation, interception stdlib)
│   │   ├── json_serializer.py  # Aplatit les logs Loguru en JSON pour le monitoring
│   │   └── langfuse_client.py  
│   │──auth/                    # Sécurité : bcrypt + JWT
│   │   ├── __init__.py         # Marqueur de package Python
│   │   └── security.py         # Hash mots de passe + création/validation des JWT
│   │──models/                  # Schémas de données partagés
│   │   ├── __init__.py         # Marqueur de package Python
│   │   └── state.py            # State partagé (mémoire commune)
│   ├── tools/                  # Outils appelés par les nœuds du graphe
│   │   ├── __init__.py         # Marqueur de package Python
│   │   ├── rag_tool.py         # Recherche FAISS + SQL + pgvector
│   │   ├── scraper_tool.py     # Recherche Web (Wikipedia)
│   │   └── horror_tools.py     # Outils annexes (âge, simulateur de survie)
│   └── graph/                  # Construction du graphe multi-agent LangGraph
│       ├── __init__.py         # Marqueur de package Python
│       ├── nodes.py            # Logique RAG, Scraper, Narration
│       ├── router.py           # Fonctions d'aiguillage conditionnel
│       └── pipeline.py         # Câblage et compilation du graphe
├── docs/                       # Sphinx (Phase 9)
├── tests/                      # Tests unitaires & intégration
├── logs/                       # Logs Loguru des 3 services, montés en volume (Phase 8.2)
├── pyproject.toml              # Dépendances et métadonnées du projet (uv)
├── app_frontend.py             # UI Streamlit (Phase 5)
├── .gitignore                  # Fichiers/dossiers exclus de Git
├── docker-compose.dev.yml      # Override dev : ports exposés + volumes de logs
├── docker-compose.yml          # Orchestration des 5 services (prod-like)
├── prometheus.yml              # Config scraping Prometheus (Phase 8.3)
├── .env                        # Variables d'environnement locales (secrets, non commité)
├── .env.docker                 # Variables d'environnement pour les conteneurs Docker
└── .env.example                # Modèle de .env à dupliquer (sans secrets)
```

# demarrer le projet #


si les conteneurs docker sont demarre:
langfuse => http://localhost:3000/
streamlit => http://localhost:8501/
fast api => https://localhost:8000/docs
prometheus => http://localhost:9092
grafana => http://localhost:3002 
uptime kuma => http://localhost:3003

si non  

```
docker compose -f docker-compose.yml -f docker-compose.dev.yml down
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

ou peut être :
```
docker compose down
docker compose up -d --build
```

verification  => ` docker ps `


## 🔒 Phase 7.3 — Communication chiffrée (TLS/HTTPS)

### Architecture
```
Navigateur (HTTP)
    ↓
Streamlit Frontend (http://localhost:8501)
    ↓ HTTPS + certificat auto-signé
Intelligence API (https://horragor-ia:8000)
```


### Certificats

- **Développement** : Certificat auto-signé généré automatiquement
  - Généré par : `scripts/generate_cert.py`
  - Stocké dans : `certs/cert.pem` + `certs/key.pem`
  - Valide pour : localhost + domaines internes Docker

- **Production** : Remplacer par un vrai certificat (Let's Encrypt, etc.)
  ```bash
  # Générer via certbot/acme
  certbot certonly --standalone -d horragor.example.com
  cp /etc/letsencrypt/live/horragor.example.com/fullchain.pem certs/cert.pem
  cp /etc/letsencrypt/live/horragor.example.com/privkey.pem certs/key.pem

### Configuration
#### Frontend (app_frontend.py)
```
SSL_VERIFY = os.getenv("SSL_CERT_PATH", "/app/certs/cert.pem")
# httpx utilise ce certificat pour faire confiance à l'API
```

#### API Intelligence (intelligence_api.Dockerfile)
```
# Uvicorn lance en HTTPS
CMD ["uvicorn", "main:app", \
     "--host", "0.0.0.0", \
     "--port", "8000", \
     "--ssl-keyfile=/app/certs/key.pem", \
     "--ssl-certfile=/app/certs/cert.pem"]
```

#### docker-compose.yml
```
services:
  horragor-ia:
    image: horragor-intelligence-api:1.0
    container_name: horragor-ia
    ports:
      - "8000:8000"
    environment:
      - PYTHONUNBUFFERED=1
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
    volumes:
      - ./intelligence_api:/app/intelligence_api
      - ./src:/app/src
      - ./data:/app/data
      - ./certs:/app/certs  # ← Certificats en volume
    networks:
      - horragor_network
    depends_on:
      - horragor-data

  horragor-front:
    image: horragor-frontend:latest
    container_name: horragor-front
    ports:
      - "8501:8501"
    environment:
      - API_BASE_URL=https://horragor-ia:8000  # ← HTTPS
      - SSL_CERT_PATH=/app/certs/cert.pem      # ← Certificat
      - PYTHONUNBUFFERED=1
    volumes:
      - ./app_frontend.py:/app/app_frontend.py
      - ./src:/app/src
      - ./certs:/app/certs  # ← Certificats en volume
    networks:
      - horragor_network
    depends_on:
      - horragor-ia

networks:
  horragor_network:
    driver: bridge
```

### Génération des certificats
#### Script — scripts/generate_cert.py
```
#!/usr/bin/env python3
"""
Générer un certificat auto-signé pour développement.
Utilisation : python scripts/generate_cert.py
"""

import os
from datetime import datetime, timedelta
from pathlib import Path

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtensionOID
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.backends import default_backend
except ImportError:
    print("❌ Erreur : cryptography non installé")
    print("   Installez avec : pip install cryptography")
    exit(1)


def generate_self_signed_cert(cert_path: str, key_path: str, days: int = 365):
    """
    Générer un certificat auto-signé et une clé privée.
    
    Args:
        cert_path: Chemin de sortie pour le certificat (.pem)
        key_path: Chemin de sortie pour la clé privée (.pem)
        days: Validité du certificat (par défaut 365 jours)
    """
    
    # Créer le répertoire s'il n'existe pas
    cert_dir = Path(cert_path).parent
    cert_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"🔐 Génération du certificat auto-signé...")
    print(f"   Répertoire : {cert_dir}")
    
    # Générer la clé privée
    print("   → Génération de la clé RSA 2048 bits...")
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend()
    )
    
    # Créer le sujet et l'émetteur (self-signed)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "FR"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "IDF"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Paris"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Horragor Dev"),
        x509.NameAttribute(NameOID.COMMON_NAME, "horragor-ia"),
    ])
    
    # Construire le certificat
    print("   → Construction du certificat X.509...")
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=days))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.DNSName("horragor-ia"),
                x509.DNSName("127.0.0.1"),
            ]),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=False, path_length=None),
            critical=True,
        )
        .sign(private_key, hashes.SHA256(), default_backend())
    )
    
    # Sauvegarder la clé privée
    print(f"   → Sauvegarde de la clé privée : {key_path}")
    with open(key_path, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption()
        ))
    os.chmod(key_path, 0o600)  # Permissions restrictives
    
    # Sauvegarder le certificat
    print(f"   → Sauvegarde du certificat : {cert_path}")
    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))
    
    print(f"\n✅ Certificat généré avec succès !")
    print(f"   Valide pour : {days} jours")
    print(f"   Domaines : localhost, horragor-ia, 127.0.0.1")
    print(f"\n📝 À intégrer dans :")
    print(f"   - intelligence_api.Dockerfile")
    print(f"   - docker-compose.yml (volumes)")
    print(f"   - app_frontend.py (SSL_CERT_PATH)")


if __name__ == "__main__":
    cert_path = Path(__file__).parent.parent / "certs" / "cert.pem"
    key_path = Path(__file__).parent.parent / "certs" / "key.pem"
    
    generate_self_signed_cert(str(cert_path), str(key_path))
```

#### Lancer la génération
```
# Installation de la dépendance
uv pip install cryptography

# Générer les certificats
python scripts/generate_cert.py
```

### Tests
```
# Vérifier que l'API est en HTTPS
docker logs horragor-ia | grep "https://"

# Résultat attendu :
INFO:     Uvicorn running on https://0.0.0.0:8000 (Press CTRL+C to quit)

# Vérifier les requêtes authentifiées
docker logs horragor-ia | grep "POST /auth/login"

# Résultat attendu :
INFO:     172.21.0.4:57100 - "POST /auth/login HTTP/1.1" 200 OK
✅ Utilisateur authentifié : admin

# Vérifier les requêtes au chat
docker logs horragor-ia | grep "POST /chat"

# Résultat attendu :
INFO:     172.21.0.4:57146 - "POST /chat HTTP/1.1" 200 OK

# Tester manuellement
curl -X POST https://localhost:8000/auth/login \
  --cacert certs/cert.pem \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"motdepasse123"}'
```
