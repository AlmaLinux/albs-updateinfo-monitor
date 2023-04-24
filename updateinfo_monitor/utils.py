import copy
import datetime
import hashlib
import logging
import pprint
import urllib.parse
from pathlib import Path
from typing import Iterator

import createrepo_c
import requests
import yaml
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from updateinfo_monitor import models
from updateinfo_monitor.config import settings
from updateinfo_monitor.database import get_session
from updateinfo_monitor.schemas import (
    Distribution,
    Module,
    Package,
    RepodataCacheResult,
    RepomdRecord,
    Repository,
)


def configure_logger():
    logging.basicConfig(
        format="%(asctime)s %(levelname)-5s %(message)s",
        level=settings.logging_level,
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def get_repo_to_index() -> Repository | None:
    delta = datetime.datetime.utcnow() - datetime.timedelta(
        minutes=settings.index_interval,
    )
    query = select(models.Repository).where(
        models.Repository.is_old.is_(False),
        models.Repository.check_ts.is_(None)
        | (models.Repository.check_ts < delta),
    )
    with get_session() as session:
        db_repo = session.execute(query).scalars().first()
        if not db_repo:
            return
        return Repository.from_orm(db_repo)


def update_repo_values(repo: Repository):
    with get_session() as session:
        session.execute(
            update(models.Repository)
            .where(models.Repository.id == repo.id)
            .values(
                check_ts=datetime.datetime.utcnow(),
                last_error=repo.last_error,
                repomd_checksum=repo.repomd_checksum,
                check_result=repo.check_result,
                check_result_checksum=repo.check_result_checksum,
            )
        )
        session.commit()


def init_cache_dir(repo: Repository) -> Path:
    cache_dir = Path(settings.repodata_cache_dir, repo.full_name)
    repodata_dir = Path(cache_dir, "repodata")
    if not repodata_dir.exists():
        repodata_dir.mkdir(parents=True)
    return cache_dir


def download_file_if_changed(
    src_url: str,
    dst_path: Path,
    etag: str = "",
) -> tuple[bool, str]:
    headers = {"If-None-Match": etag} if etag else None
    with requests.get(src_url, headers=headers, stream=True) as response:
        response.raise_for_status()
        if response.status_code == requests.codes.not_modified:
            return False, etag
        with open(dst_path, "wb") as fd:
            for chunk in response.iter_content(chunk_size=1024):
                fd.write(chunk)
            return True, response.headers.get("ETag", "")


def get_file_checksum(
    file_path: Path,
    checksum_type: str = "sha256",
    buff_size: int = 1048576,
) -> str:
    hasher = hashlib.new(checksum_type)
    with open(file_path, "rb") as fd:
        buff = fd.read(buff_size)
        while len(buff):
            hasher.update(buff)
            buff = fd.read(buff_size)
    return hasher.hexdigest()


def get_string_checksum(string: str) -> str:
    return hashlib.sha256(string.encode()).hexdigest()


def cleanup_repodata_dir(repodata_path: Path):
    if not repodata_path.exists():
        repodata_path.mkdir()
        return
    for path in repodata_path.glob("**/*"):
        if path.name == "repomd.xml":
            continue
        if path.is_file():
            path.unlink()
            continue
        path.rmdir()


def iter_repodata_records(
    repomd_path: Path,
    repodata_path: Path,
) -> Iterator[RepomdRecord]:
    repomd = createrepo_c.Repomd(str(repomd_path))
    for rec in repomd.records:
        yield RepomdRecord(
            **{
                "checksum": rec.checksum,
                "checksum_type": rec.checksum_type,
                "checksum_open": rec.checksum_open,
                "checksum_open_type": rec.checksum_open_type,
                "timestamp": rec.timestamp,
                "location_href": rec.location_href,
                "size_open": rec.size_open,
                "size": rec.size,
                "data_type": rec.type,
                "path": Path(repodata_path, Path(rec.location_href).name),
            }
        )


def update_repodata_cache(repo: Repository) -> RepodataCacheResult:
    cache_dir = init_cache_dir(repo)
    logging.info(
        "(%s) Created %s repodata cache directory",
        repo.full_name,
        cache_dir,
    )
    cache_result = RepodataCacheResult(
        repo_name=repo.name,
        repo_arch=repo.arch,
        cache_dir=cache_dir,
    )
    repodata_path = Path(cache_dir, "repodata")
    repomd_path = Path(repodata_path, "repomd.xml")
    repomd_url = urllib.parse.urljoin(repo.url, "repodata/repomd.xml")
    repomd_changed, cache_result.repomd_etag = download_file_if_changed(
        repomd_url,
        repomd_path,
        repo.repomd_etag,
    )
    if not repomd_changed:
        logging.info(
            "%s repomd.xml ETag is not changed, skipping repodata update",
            repo.full_name,
        )
        for rec in iter_repodata_records(repomd_path, repodata_path):
            cache_result.add_repomd_record(rec)
        return cache_result
    cache_result.repomd_checksum = get_file_checksum(repomd_path)
    if cache_result.repomd_checksum == repo.repomd_checksum:
        logging.info(
            "%s repomd.xml checksum is not changed, skipping repodata update",
            repo.full_name,
        )
        for rec in iter_repodata_records(repomd_path, repodata_path):
            cache_result.add_repomd_record(rec)
        return cache_result
    cleanup_repodata_dir(repodata_path)
    for rec in iter_repodata_records(repomd_path, repodata_path):
        src_url = urllib.parse.urljoin(repo.url, rec.location_href)
        download_file_if_changed(src_url, rec.path)
        rec_checksum = get_file_checksum(rec.path, rec.checksum_type)
        if rec_checksum != rec.checksum:
            raise ValueError(f"{src_url} download failed: wrong checksum")
        cache_result.add_repomd_record(rec)
    cache_result.changed = True
    return cache_result


def updateinfo_from_file(updateinfo_path: Path) -> createrepo_c.UpdateInfo:
    try:
        updateinfo = createrepo_c.UpdateInfo(str(updateinfo_path))
    except Exception as exc:
        logging.exception(
            "Cannot parse updateinfo.xml content:",
        )
        raise exc
    return updateinfo


def check_repo_updateinfo(
    repo: Repository,
    updateinfo: createrepo_c.UpdateInfo,
    repo_packages: dict[str, Package],
    repo_modules: dict[str, Module],
):
    with get_session() as session:
        db_records = (
            session.execute(
                select(models.UpdateRecord).where(
                    models.UpdateRecord.repository_id == repo.id
                ),
            )
            .scalars()
            .all()
        )
        db_records = {rec.record_id: rec for rec in db_records}
    repo_check_results = {}
    if repo.check_result:
        repo_check_results = copy.deepcopy(repo.check_result)
    records_to_add = []
    for record in updateinfo.updates:
        db_record = db_records.get(record.id)
        if db_record and db_record.updated_date == record.updated_date:
            logging.info(
                "(repo=%s) skipping %s record, updated_date is not changed",
                repo.full_name,
                record.id,
            )
            continue
        if not db_record:
            db_record = models.UpdateRecord(
                record_id=record.id,
                updated_date=record.updated_date,
                repository_id=repo.id,
            )
        db_record.updated_date = record.updated_date

        logging.info(
            "(repo=%s) processing %s record",
            repo.full_name,
            record.id,
        )
        missing_packages = []
        missing_modules = []
        missing_modular_packages = []
        for collection in record.collections:
            cr_module = collection.module
            modular = bool(cr_module)
            modular_artifacts = []
            module_exist = False
            if modular:
                module = Module.from_cr_updatemodule(cr_module)
                repo_module = repo_modules.get(module.nvsca)
                if repo_module:
                    module_exist = True
                    modular_artifacts = repo_module.artifacts
                if not module_exist:
                    missing_modules.append(module.nvsca)
            for cr_package in collection.packages:
                package = Package.from_cr_updatepackage(cr_package)
                nevra = package.nevra
                if nevra not in repo_packages:
                    missing_packages.append(nevra)
                if modular and module_exist and nevra not in modular_artifacts:
                    missing_modular_packages.append(nevra)
        records_to_add.append(db_record)

        if (
            not missing_modules
            and not missing_modular_packages
            and not missing_packages
        ):
            repo_check_results.pop(record.id, None)
            continue
        repo_check_results[record.id] = {
            "missing_packages": missing_packages,
            "missing_modular_packages": missing_modular_packages,
            "missing_modules": missing_modules,
        }
    repo.check_result = repo_check_results
    with get_session() as session:
        session.add_all(records_to_add)
        session.commit()
    logging.info(
        "(repo=%s) repo_check_results:\n%s",
        repo.full_name,
        pprint.pformat(repo_check_results),
    )


def index_repo(repo: Repository):
    cache_result = update_repodata_cache(repo)
    if not cache_result.changed:
        logging.info("%s metadata is not changed, skipping it", repo.full_name)
        return
    updateinfo_record = cache_result.get_repomd_record("updateinfo")
    if not updateinfo_record:
        raise ValueError("Cannot parse updatinfo, updateinfo.xml is missing")
    updateinfo = updateinfo_from_file(updateinfo_record.path)
    repo_packages = cache_result.parse_packages()
    repo_modules = cache_result.parse_modules()
    for old_repo in repo.old_repositories:
        try:
            old_repo_cache_result = update_repodata_cache(old_repo)
            repo_packages.update(old_repo_cache_result.parse_packages())
            repo_modules.update(old_repo_cache_result.parse_modules())
        except Exception:
            logging.exception(
                "(%s) Cannot parse old repodata:",
                old_repo.full_name,
            )
            continue
        old_repo.repomd_checksum = old_repo_cache_result.repomd_checksum
        update_repo_values(old_repo)
    check_repo_updateinfo(
        repo=repo,
        updateinfo=updateinfo,
        repo_packages=repo_packages,
        repo_modules=repo_modules,
    )
    repo.repomd_checksum = cache_result.repomd_checksum


def init_slack_client() -> WebClient:
    return WebClient(
        token=settings.slack_bot_token,
    )


def send_notification(repo: Repository, slack_client: WebClient):
    if not repo.check_result or not settings.slack_notifications_enabled:
        logging.debug(
            "Skip sending notification, check_result field is empty "
            "or sending notifications is disabled",
        )
        return
    formatted_content = pprint.pformat(repo.check_result)
    check_result_checksum = get_string_checksum(formatted_content)
    if check_result_checksum == repo.check_result_checksum:
        logging.debug(
            "Skip sending notification, check_result_checksum is not changed",
        )
        return
    try:
        result = slack_client.files_upload_v2(
            channel=settings.slack_channel_id,
            filename=f"{repo.full_name}_result.json",
            initial_comment=f"Check results for *{repo.full_name}* repository",
            content=formatted_content,
        )
        repo.check_result_checksum = check_result_checksum
        logging.debug("SlackApi response:\n%s", result)
    except SlackApiError:
        logging.exception(
            "Cannot post message to slack channel: %s",
            settings.slack_channel_id,
        )


def load_repositories_from_file(filepath: Path):
    def process_repo() -> models.Repository:
        repo_url = repo.url.replace("$basearch", repo.arch)
        if repo.arch == "i686":
            repo_url = repo_url.replace("/almalinux/", "/vault/")
        repo_obj = repos_mapping.get(repo.full_name)
        if not repo_obj:
            repo_obj = models.Repository(**repo.dict_for_create())
        for attr, value in (
            ("url", repo_url),
            ("debuginfo", repo.debuginfo),
        ):
            setattr(repo_obj, attr, value)
        repos_to_add.append(repo_obj)
        return repo_obj

    def process_old_repo():
        repo_name = repo_obj.name.replace(
            f"-{distr.version}-",
            f"-{old_version}-",
        )
        repo_url = repo_obj.url.replace("/almalinux/", "/vault/").replace(
            f"/{distr.version}/",
            f"/{old_version}/",
        )
        old_repo_obj = next(
            (
                old_repo
                for old_repo in repo_obj.old_repositories
                if old_repo.name == repo_name
                and old_repo.arch == repo_obj.arch
            ),
            None,
        )
        if not old_repo_obj:
            old_repo_obj = models.Repository(
                name=repo_name,
                arch=repo_obj.arch,
                url=repo_url,
                debuginfo=repo_obj.debuginfo,
                is_old=True,
            )
        for attr, value in (
            ("url", repo_url),
            ("debuginfo", repo.debuginfo),
        ):
            setattr(old_repo_obj, attr, value)
        repo_obj.old_repositories.append(old_repo_obj)
        repos_to_add.append(old_repo_obj)

    repos_to_add = []
    with open(filepath, "rb") as fd:
        data = yaml.safe_load(fd)
        repos_mapping = {}
        with get_session() as session:
            db_repos = (
                session.execute(
                    select(models.Repository).options(
                        joinedload(models.Repository.old_repositories),
                    )
                )
                .scalars()
                .all()
            )
            repos_mapping.update({repo.full_name: repo for repo in db_repos})
            for distr in data:
                distr = Distribution(**distr)
                logging.info(
                    "Adding/updating %s distribution configuration",
                    distr.name,
                )
                for repo in distr.repositories:
                    for arch in distr.arches:
                        if arch in repo.exclude_arch:
                            continue
                        repo.arch = arch
                        repo_obj = process_repo()
                        for old_version in distr.old_versions:
                            process_old_repo()
                for repo in distr.sources:
                    repo.arch = "src"
                    repo_obj = process_repo()
                    for old_version in distr.old_versions:
                        process_old_repo()
            session.add_all(repos_to_add)
            session.commit()
