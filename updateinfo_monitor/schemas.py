import logging
from datetime import datetime
from pathlib import Path

import createrepo_c
import gi
from pydantic import AnyHttpUrl, BaseModel, Field

gi.require_version("Modulemd", "2.0")
from gi.repository import Modulemd


class Repository(BaseModel):
    id: int | None = None
    name: str
    arch: str = ""
    description: str = ""
    url: AnyHttpUrl
    exclude_arch: list[str] = Field(default_factory=list)
    debuginfo: bool = False
    repomd_etag: str | None = None
    repomd_checksum: str | None = None
    check_ts: datetime | None = None
    last_error: str | None = None
    check_result: dict | None = Field(default_factory=dict)
    check_result_checksum: str | None = None

    class Config:
        orm_mode = True

    @property
    def full_name(self) -> str:
        return f"{self.name}.{self.arch}"

    def dict_for_create(self):
        return {
            "name": self.name,
            "arch": self.arch,
            "url": self.url,
            "debuginfo": self.debuginfo,
        }


class Distribution(BaseModel):
    name: str
    version: str
    arches: list[str]
    repositories: list[Repository]
    sources: list[Repository]


class RepomdRecord(BaseModel):
    data_type: str
    checksum: str
    checksum_type: str
    checksum_open: str | None = None
    checksum_open_type: str | None = None
    timestamp: int
    location_href: str
    size: int
    size_open: int
    path: Path | None = None


class Package(BaseModel):
    name: str
    epoch: str
    version: str
    release: str
    arch: str
    location_href: str = ""
    cr_nevra: str = ""

    @staticmethod
    def from_cr_package(cr_package: createrepo_c.Package) -> "Package":
        return Package(
            name=cr_package.name,
            epoch=cr_package.epoch,
            version=cr_package.version,
            release=cr_package.release,
            arch=cr_package.arch,
            location_href=cr_package.location_href,
            cr_nevra=cr_package.nevra(),
        )

    @staticmethod
    def from_cr_updatepackage(
        cr_package: createrepo_c.UpdateCollectionPackage,
    ) -> "Package":
        return Package(
            name=cr_package.name,
            epoch=cr_package.epoch,
            version=cr_package.version,
            release=cr_package.release,
            arch=cr_package.arch,
        )

    @property
    def nevra(self) -> str:
        nevra = self.cr_nevra
        if not nevra:
            nevra = f"{self.name}-{self.epoch}:{self.version}-{self.release}.{self.arch}"
        return nevra


class Module(BaseModel):
    name: str
    stream: str
    version: int
    context: str
    arch: str
    artifacts: list[str] = Field(default_factory=list)

    @property
    def nvsca(self) -> str:
        return ":".join(
            (
                self.name,
                str(self.version),
                self.stream,
                self.context,
                self.arch,
            )
        )

    @staticmethod
    def from_libmodulemd_stream(stream) -> "Module":
        return Module(
            name=stream.get_module_name(),
            stream=stream.get_stream_name(),
            version=stream.get_version(),
            context=stream.get_context(),
            arch=stream.get_arch(),
            artifacts=stream.get_rpm_artifacts(),
        )

    @staticmethod
    def from_cr_updatemodule(
        cr_module: createrepo_c.UpdateCollectionModule,
    ) -> "Module":
        return Module(
            name=cr_module.name,
            stream=cr_module.stream,
            version=cr_module.version,
            context=cr_module.context,
            arch=cr_module.arch,
        )


class RepodataCacheResult(BaseModel):
    repo_name: str
    repo_arch: str
    cache_dir: Path
    changed: bool = False
    repomd_checksum: str = ""
    repomd_records: dict = Field(default_factory=dict)
    repomd_etag: str = ""

    def add_repomd_record(self, record: RepomdRecord):
        self.repomd_records[record.data_type] = record

    def get_repomd_record(self, data_type: str) -> RepomdRecord | None:
        return self.repomd_records.get(data_type)

    def parse_packages(self) -> dict[str, Package]:
        def warningcb(warning_type, message):
            logging.debug("PARSER WARNING: %s", message)
            return True

        packages = {}
        primary_record = self.get_repomd_record("primary")
        filelists_record = self.get_repomd_record("filelists")
        other_record = self.get_repomd_record("other")
        if not primary_record or not filelists_record or not other_record:
            raise ValueError(
                "Cannot parse packages, some of repomd records is missing",
            )
        package_iterator = createrepo_c.PackageIterator(
            primary_path=str(primary_record.path),
            filelists_path=str(filelists_record.path),
            other_path=str(other_record.path),
            warningcb=warningcb,
        )
        for cr_pkg in package_iterator:
            package = Package.from_cr_package(cr_pkg)
            packages[package.nevra] = package
            del cr_pkg
        return packages

    def parse_modules(self) -> dict[str, Module]:
        modules = {}
        modules_record = self.get_repomd_record("modules")
        if not modules_record:
            return modules
        idx = Modulemd.ModuleIndex.new()
        ret, _ = idx.update_from_file(str(modules_record.path), strict=True)
        if not ret:
            raise ValueError("Cannot parse modules.yaml, loading failed")
        supported_mdversion = Modulemd.ModuleStreamVersionEnum.TWO
        for module_name in idx.get_module_names():
            lib_module = idx.get_module(module_name)
            for stream in lib_module.get_all_streams():
                stream.validate()
                stream_mdversion = stream.get_mdversion()
                if stream_mdversion != supported_mdversion:
                    raise NotImplementedError(
                        f"{stream_mdversion} module metadata version is not supported yet"
                    )
                module = Module.from_libmodulemd_stream(stream)
                modules[module.nvsca] = module
        return modules
