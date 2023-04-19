import logging
import time
from traceback import format_exc

from updateinfo_monitor.config import settings
from updateinfo_monitor.utils import (
    get_repo_to_index,
    index_repo,
    update_repo_values,
)


def start_monitoring_loop():
    while True:
        repo = get_repo_to_index()
        if not repo:
            logging.info(
                "All repositories are up to date, sleeping for %d seconds",
                settings.loop_sleep_time,
            )
            time.sleep(settings.loop_sleep_time)
            continue
        try:
            index_repo(repo)
        except Exception:
            logging.exception("Cannot index repo: %s", repo.full_name)
            repo.last_error = format_exc()
        finally:
            update_repo_values(repo)
        time.sleep(10)


if __name__ == "__main__":
    start_monitoring_loop()
