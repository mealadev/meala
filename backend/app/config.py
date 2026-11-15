from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./meala_local.db"
    org_api_key: str = "change_me_org_ingestion_key"
    cors_origins: str = "http://localhost:8080,http://localhost:3000"
    raw_logs_dir: str = "./data/raw_logs"
    parquet_dir: str = "./data/parquet_store"
    seed_demo_flights: bool = True

    class Config:
        env_file = ".env"


settings = Settings()
