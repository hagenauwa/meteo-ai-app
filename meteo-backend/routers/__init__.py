from .weather import router as weather
from .cities import router as cities
from .ml import router as ml
from .admin import router as admin
from .supporters import router as supporters
from .advanced import router as advanced
from .telegram import router as telegram

__all__ = [
    "weather",
    "cities",
    "ml",
    "admin",
    "supporters",
    "advanced",
    "telegram",
]
