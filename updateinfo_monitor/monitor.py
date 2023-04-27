import logging
import time
from traceback import format_exc

from updateinfo_monitor.config import settings
from updateinfo_monitor.utils import (
    get_repo_to_index,
    index_repo,
    init_slack_client,
    send_notification,
    update_repo_values,
)


def start_monitoring_loop():
    slack_client = init_slack_client()
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
            send_notification(repo, slack_client)
            update_repo_values(repo)


if __name__ == "__main__":
    start_monitoring_loop()
