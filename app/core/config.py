from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "attendance-system"
    app_env: str = "development"
    debug: bool = True
    secret_key: str = "change-me-in-production"
    verification_code_key: str = ""

    # Individual DB vars (local dev / legacy)
    db_host: str = "127.0.0.1"
    db_port: int = 3306
    db_name: str = "attendance_system"
    db_user: str = "root"
    db_password: str = ""

    # Full URL override (Railway / Heroku / any hosted MySQL)
    database_url: str = ""

    selfie_storage_dir: str = ""
    geoip_city_db: str = ""
    geoip_asn_db: str = ""

    @property
    def resolved_database_url(self) -> str:
        """Return the database URL, building it from components if needed."""
        if self.database_url:
            url = self.database_url
            # Railway / Heroku give `mysql://` — PyMySQL needs `mysql+pymysql://`
            if url.startswith("mysql://"):
                url = "mysql+pymysql://" + url[len("mysql://"):]
            return url
        return (
            f"mysql+pymysql://{self.db_user}:{self.db_password}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}?charset=utf8mb4"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
