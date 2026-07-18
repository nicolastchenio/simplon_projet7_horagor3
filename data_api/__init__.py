"""
data_api
========
Micro-service d'accès aux données.

Expose une API FastAPI interne qui encapsule l'ensemble des
communications avec PostgreSQL / Supabase. Aucun autre module du
projet ne doit ouvrir de connexion directe à la base.
"""