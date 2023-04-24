from pathlib import Path

from pydantic import BaseSettings, PostgresDsn

from updateinfo_monitor.constants import INDEX_INTERVAL, LOOP_SLEEP_TIME


class Settings(BaseSettings):
    pg_dsn: PostgresDsn = (
        "postgresql+psycopg2://postgres:password@db/errata-monitor"
    )

    index_interval: int = INDEX_INTERVAL
    loop_sleep_time: int = LOOP_SLEEP_TIME
    repodata_cache_dir: Path = Path("/srv/repodata_cache_dir/")
    logging_level: str = "INFO"
    slack_notifications_enabled: bool = False
    slack_bot_token: str = ""
    slack_channel_id: str = ""


settings = Settings()
