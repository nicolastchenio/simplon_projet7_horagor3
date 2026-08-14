# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import sys

# docs/source/conf.py -> on remonte de 2 niveaux pour atteindre la racine
# du projet, là où vivent les packages "src" et "data_api".
sys.path.insert(0, os.path.abspath('../..'))

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

project = 'HorRAGor'
copyright = '2026, Nicolas Tchenio'
author = 'Nicolas Tchenio'

version = '0.1'
release = '0.1'

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx_rtd_theme',
    'myst_parser',
    'sphinxcontrib.mermaid',
]

templates_path = ['_templates']
exclude_patterns = []

# Bibliothèques tierces lourdes dont le rechargement par autodoc entre
# en conflit avec la reconstruction de schéma Pydantic v2 (ex. BaseMessage
# de langchain_core). On les mocke : nos propres modules restent
# documentés normalement, seuls les types externes ne sont pas résolus.
autodoc_mock_imports = [
    'langchain',
    'langchain_core',
    'langchain_community',
    'langchain_ollama',
    'langgraph',
    'faiss',
]

language = 'fr'

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = 'sphinx_rtd_theme'
html_static_path = ['_static']
