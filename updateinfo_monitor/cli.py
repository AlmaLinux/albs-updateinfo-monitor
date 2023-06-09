import argparse
from pathlib import Path

from updateinfo_monitor.monitor import start_monitoring_loop
from updateinfo_monitor.utils import (
    configure_logger,
    load_repositories_from_file,
)


def parse_args():
    parser = argparse.ArgumentParser(
        "albs-updateinfo-monitor",
        description="Validate updateinfo records",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="Start monitoring loop",
        required=False,
        default=True,
    )
    parser.add_argument(
        "--file",
        help="Path to .yml file with repositories for load in DB",
        required=False,
        type=Path,
    )
    return parser.parse_args()


def main():
    args = parse_args()
    configure_logger()
    if args.file:
        load_repositories_from_file(args.file)
        return
    start_monitoring_loop()


if __name__ == "__main__":
    main()
