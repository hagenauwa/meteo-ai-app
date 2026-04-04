"""
auth.py — dipendenze di autenticazione per endpoint sensibili.
"""
from fastapi import Header, HTTPException

from config import settings


def require_admin_access(x_admin_token: str | None = Header(default=None)) -> None:
    """
    In produzione richiede un token esplicito.
    In sviluppo locale permette l'accesso se il token non è configurato.
    """
    if not settings.is_production and not settings.admin_api_token:
        return

    if not settings.admin_api_token:
        raise HTTPException(
            status_code=503,
            detail="ADMIN_API_TOKEN non configurato sul server",
        )

    if x_admin_token != settings.admin_api_token:
        raise HTTPException(status_code=403, detail="Token amministratore non valido")
