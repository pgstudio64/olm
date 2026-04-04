"""Helpers partagés entre les parseurs DSL (pattern_dsl, room_dsl).

Fournit :
- DSLError : classe d'erreur de base pour tous les DSL
- strip_comment : suppression des commentaires ``--``
- parse_int : conversion token -> int avec message d'erreur clair
"""
from __future__ import annotations


class DSLError(ValueError):
    """Erreur de syntaxe ou de sémantique dans un DSL."""


def strip_comment(line: str) -> str:
    """Retire le commentaire ``--`` et les espaces de début/fin.

    Args:
        line: Ligne brute pouvant contenir un commentaire.

    Returns:
        Ligne nettoyée, potentiellement vide.
    """
    idx = line.find("--")
    if idx != -1:
        line = line[:idx]
    return line.strip()


def parse_int(token: str, name: str, context: str = "") -> int:
    """Convertit un token en entier avec message d'erreur clair.

    Args:
        token: Chaîne à convertir.
        name: Nom du champ (pour le message d'erreur).
        context: Contexte additionnel pour le message d'erreur
                 (ex. "Ligne 3").

    Returns:
        Valeur entière.

    Raises:
        DSLError: Si le token n'est pas un entier valide.
    """
    try:
        return int(token)
    except ValueError:
        prefix = f"{context} : " if context else ""
        raise DSLError(
            f"{prefix}{name} invalide '{token}' (entier attendu)"
        ) from None
