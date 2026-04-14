"""Application configuration classes."""
import os
from dotenv import load_dotenv
from sqlalchemy.pool import StaticPool

load_dotenv()


class BaseConfig:
    """Base configuration shared across all environments."""
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-change-in-production")
    SQLALCHEMY_TRACK_MODIFICATIONS = False


class DevelopmentConfig(BaseConfig):
    """Development configuration."""
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/diabetes_db"
    )
    CORS_ORIGINS = "*"


class ProductionConfig(BaseConfig):
    """Production configuration (Railway / HPC deployment)."""
    DEBUG = False

    # Railway Postgres uses postgres:// but SQLAlchemy requires postgresql://
    _db_url = os.getenv("DATABASE_URL", "")
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url

    CORS_ORIGINS = os.getenv(
        "CORS_ORIGINS", "https://*.vercel.app,https://*.up.railway.app"
    ).split(",")


class TestingConfig(BaseConfig):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    SQLALCHEMY_ENGINE_OPTIONS = {
        "connect_args": {"check_same_thread": False},
        "poolclass": StaticPool,
    }
    CORS_ORIGINS = "*"


config_by_name = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestingConfig,
}
