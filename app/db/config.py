from functools import lru_cache
from pydantic_settings import BaseSettings
from typing import Optional
import os


class Settings(BaseSettings):
    APP_NAME: str = "Eina Mapeig Variables"
    APP_VERSION: str = "1.0.0"
    ENV: str = "dev"

    # Clave secreta para SessionMiddleware
    SECRET_KEY: str

    # Base de datos principal (PostgreSQL)
    DATABASE_URL: str

    # SMTP para envío de correos (reset contraseña, invitaciones)
    SMTP_SERVER: Optional[str] = None
    SMTP_PORT: int = 587
    SMTP_USER: Optional[str] = None
    SMTP_PASSWORD: Optional[str] = None
    SENDER_EMAIL: Optional[str] = None

    # URL pública de la app (para generar enlaces en correos)
    FRONTEND_URL: str = os.getenv("FRONTEND_URL_server", "http://localhost:8092")

    model_config = {
        # docker-compose carga las vars de .env directamente en el entorno;
        # este fallback sirve para desarrollo local sin docker-compose
        "env_file": ".env",
        "case_sensitive": True,
        "extra": "allow"
    }


@lru_cache()
def get_settings() -> Settings:
    return Settings()
