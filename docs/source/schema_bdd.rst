Schéma relationnel de la base de données
==========================================

Ce document est **généré automatiquement** par ``scripts/generate_db_schema_doc.py`` à partir d'une introspection du catalogue PostgreSQL de Supabase (schéma ``public``). Relancez ce script si le schéma évolue :

::

    uv run python scripts/generate_db_schema_doc.py

Cartographie des relations
----------------------------

.. mermaid::

   erDiagram
       acteur {
           integer id_acteur PK
           character_varying_255 nom
       }
       film {
           integer id_film PK
           character_varying_255 titre
           integer annee_sortie
           character_varying_10 langue_originale
           text synopsis
           text tagline
           integer duree
           bigint budget
           bigint revenue
           integer id_realisateur FK
           vector_768 embedding
       }
       film_acteur {
           integer id_film PK
           integer id_acteur PK
       }
       film_genre {
           integer id_film PK
           integer id_genre PK
       }
       film_societe_production {
           integer id_film PK
           integer id_societe PK
       }
       genre {
           integer id_genre PK
           character_varying_100 nom
       }
       realisateur {
           integer id_realisateur PK
           character_varying_255 nom
       }
       score {
           integer id_score PK
           numeric_3_1 score_tmdb
           numeric_3_1 score_imdb
           numeric_5_2 score_rotten_critics
           numeric_5_2 score_rotten_audience
           numeric_3_1 score_horragor
           integer id_film FK
       }
       societe_production {
           integer id_societe PK
           character_varying_255 nom
       }
       realisateur ||--o{ film : "id_realisateur"
       film ||--o{ film_acteur : "id_film"
       acteur ||--o{ film_acteur : "id_acteur"
       film ||--o{ film_genre : "id_film"
       genre ||--o{ film_genre : "id_genre"
       film ||--o{ film_societe_production : "id_film"
       societe_production ||--o{ film_societe_production : "id_societe"
       film ||--o{ score : "id_film"

Table ``acteur``
----------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_acteur
     - integer
     - Non
     - PK
   * - nom
     - character varying(255)
     - Non
     - 

Table ``film``
--------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_film
     - integer
     - Non
     - PK
   * - titre
     - character varying(255)
     - Non
     - 
   * - annee_sortie
     - integer
     - Oui
     - 
   * - langue_originale
     - character varying(10)
     - Oui
     - 
   * - synopsis
     - text
     - Oui
     - 
   * - tagline
     - text
     - Oui
     - 
   * - duree
     - integer
     - Oui
     - 
   * - budget
     - bigint
     - Oui
     - 
   * - revenue
     - bigint
     - Oui
     - 
   * - id_realisateur
     - integer
     - Non
     - FK → realisateur.id_realisateur
   * - embedding
     - vector(768)
     - Oui
     - 

Table ``film_acteur``
---------------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_film
     - integer
     - Non
     - PK
   * - id_acteur
     - integer
     - Non
     - PK

Table ``film_genre``
--------------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_film
     - integer
     - Non
     - PK
   * - id_genre
     - integer
     - Non
     - PK

Table ``film_societe_production``
---------------------------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_film
     - integer
     - Non
     - PK
   * - id_societe
     - integer
     - Non
     - PK

Table ``genre``
---------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_genre
     - integer
     - Non
     - PK
   * - nom
     - character varying(100)
     - Non
     - 

Table ``realisateur``
---------------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_realisateur
     - integer
     - Non
     - PK
   * - nom
     - character varying(255)
     - Non
     - 

Table ``score``
---------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_score
     - integer
     - Non
     - PK
   * - score_tmdb
     - numeric(3,1)
     - Oui
     - 
   * - score_imdb
     - numeric(3,1)
     - Oui
     - 
   * - score_rotten_critics
     - numeric(5,2)
     - Oui
     - 
   * - score_rotten_audience
     - numeric(5,2)
     - Oui
     - 
   * - score_horragor
     - numeric(3,1)
     - Oui
     - 
   * - id_film
     - integer
     - Non
     - FK → film.id_film

Table ``societe_production``
----------------------------

.. list-table::
   :header-rows: 1

   * - Colonne
     - Type
     - Nullable
     - Clé
   * - id_societe
     - integer
     - Non
     - PK
   * - nom
     - character varying(255)
     - Non
     - 
