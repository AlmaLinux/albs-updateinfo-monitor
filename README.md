# AlmaLinux OS updateinfo monitor

## Config

Create the `vars.env` file with the following variables defined:
    ```sh
    POSTGRES_PASSWORD="password"
    POSTGRES_DB="errata-monitor"
    PG_DSN="postgresql+psycopg2://postgres:password@db/errata-monitor"

## Running docker-compose

You can start the service using the Docker Compose tool.

Pre-requisites:
* `docker` and `docker-compose` tools are installed and set up;

To start the service, run the following command: `docker-compose up -d`.

To rebuild images after your local changes, just run: `docker-compose restart updateinfo-monitor`

To load the reference data, run the following command: `docker-compose run --rm updateinfo-monitor bash -c 'poetry run python updateinfo_monitor/cli.py --load --file data/almalinux.yml'`
