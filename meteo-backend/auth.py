"""
auth.py — dipendenze di autenticazione per endpoint sensibili.
"""

import secrets

from fastapi import Header, HTTPException

from config import settings


def require_admin_access(x_admin_token: str | None = Header(default=None)) -> None:
    """
    In produzione richiede un token esplicito.
    In sviluppo locale permette l'accesso se il token non è configurato.
    """
    if not settings.admin_api_token:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_API_TOKEN non configurato sul server",
        )

    # Confronto a tempo costante per evitare timing attack sul token.
    if not secrets.compare_digest(x_admin_token or "", settings.admin_api_token):
        raise HTTPException(status_code=403, detail="Token amministratore non valido")
