from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from cadis.cdn.archive import safe_extract_tar_gz
from cadis.cdn.hashing import bundle_checksum_from_files, parse_sha256_file, sha256_file
from cadis.cdn.runtime_compat import validate_manifest_runtime_compatibility
from cadis.cdn.transport import read_bytes_url, read_json_url, read_text_url, repo_relative_url

DEFAULT_REQUIRED_FILES = (
    "dataset_release_manifest.json",
    "geometry.ffsf",
    "geometry_meta.json",
    "runtime_policy.json",
)
DEFAULT_MANIFEST_NAME = "dataset_release_manifest.json"
DEFAULT_MANIFEST_PROFILE = "cadis.dataset.release"
DEFAULT_RUNTIME_POLICY_FILE = "runtime_policy.json"
DEFAULT_DATASET_MANIFEST_URL = (
    "https://raw.githubusercontent.com/isemptyc/cadis-dataset/main/releases/dataset_manifest.json"
)


def _noop_validate_manifest(_manifest: dict[str, Any]) -> None:
    return None


def _noop_validate_dataset_dir(_dataset_dir: Path) -> None:
    return None


def required_files_present(
    dataset_dir: Path,
    *,
    required_files: tuple[str, ...] = DEFAULT_REQUIRED_FILES,
) -> list[str]:
    return [name for name in required_files if not (dataset_dir / name).exists()]


def parse_version_for_sort(raw: str) -> tuple[int, ...]:
    value = raw.strip()
    if value.startswith("v"):
        value = value[1:]
    parts = value.split(".")
    if not parts or any(not p.isdigit() for p in parts):
        return tuple()
    return tuple(int(p) for p in parts)


def validate_cached_dataset_dir(
    dataset_dir: Path,
    *,
    validate_dataset_dir: Callable[[Path], None],
    required_files: tuple[str, ...] = DEFAULT_REQUIRED_FILES,
) -> bool:
    if required_files_present(dataset_dir, required_files=required_files):
        return False
    validate_dataset_dir(dataset_dir)
    return True


def find_local_cached_dataset(
    *,
    iso2: str,
    cache_root: Path,
    dataset_id: str,
    validate_dataset_dir: Callable[[Path], None],
    required_files: tuple[str, ...] = DEFAULT_REQUIRED_FILES,
) -> dict[str, Any] | None:
    versions_root = cache_root / iso2 / dataset_id
    if not versions_root.exists():
        return None

    candidates: list[tuple[tuple[int, ...], str, Path]] = []
    for entry in versions_root.iterdir():
        if not entry.is_dir():
            continue
        parsed = parse_version_for_sort(entry.name)
        if parsed:
            candidates.append((parsed, entry.name, entry))
    candidates.sort(reverse=True)

    for _, version, path in candidates:
        if validate_cached_dataset_dir(
            path,
            validate_dataset_dir=validate_dataset_dir,
            required_files=required_files,
        ):
            return {
                "country_iso2": iso2,
                "dataset_id": dataset_id,
                "dataset_version": version,
                "dataset_dir": str(path),
                "used_cached_dataset": True,
            }
    return None


def resolve_latest_release(
    *,
    country_iso2: str,
    dataset_manifest_url: str,
    timeout_sec: int,
    validate_release_manifest_compatibility: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    root_manifest = read_json_url(dataset_manifest_url, timeout_sec=timeout_sec)
    countries = root_manifest.get("countries")
    if not isinstance(countries, dict):
        raise ValueError("dataset_manifest.json missing countries object.")

    iso2 = country_iso2.strip().upper()
    country_block = countries.get(iso2)
    if not isinstance(country_block, dict):
        raise ValueError(f"dataset_manifest.json does not include country {iso2}.")

    dataset_id = f"{iso2.lower()}.admin"
    release_entry = country_block.get(dataset_id)
    if not isinstance(release_entry, dict):
        raise ValueError(f"dataset_manifest.json missing dataset entry {dataset_id} for {iso2}.")

    latest = release_entry.get("latest")
    manifest_rel = release_entry.get("manifest")
    if not isinstance(latest, str) or not latest.strip():
        raise ValueError("dataset_manifest latest is missing/invalid.")
    if not isinstance(manifest_rel, str) or not manifest_rel.strip():
        raise ValueError("dataset_manifest manifest path is missing/invalid.")

    release_manifest_url = repo_relative_url(dataset_manifest_url, manifest_rel)
    release_manifest = read_json_url(release_manifest_url, timeout_sec=timeout_sec)
    manifest_country = str(release_manifest.get("country_iso", "")).strip().upper()
    if manifest_country != iso2:
        raise ValueError(
            f"Release manifest country mismatch: expected={iso2} actual={manifest_country!r}."
        )

    release_dataset_id = release_manifest.get("dataset_id")
    release_version = release_manifest.get("dataset_version")
    if not isinstance(release_dataset_id, str) or not release_dataset_id.strip():
        raise ValueError("Release manifest missing dataset_id.")
    if not isinstance(release_version, str) or not release_version.strip():
        raise ValueError("Release manifest missing dataset_version.")
    if release_version.strip() != latest.strip():
        raise ValueError(f"Release version mismatch: latest={latest!r} manifest={release_version!r}.")

    validate_release_manifest_compatibility(release_manifest)
    base_release_url = release_manifest_url.rsplit("/", 1)[0] + "/"
    package_url = urljoin(base_release_url, "dataset_package.tar.gz")
    package_sha_url = urljoin(base_release_url, "dataset_package.tar.gz.sha256")

    return {
        "country_iso2": iso2,
        "dataset_manifest_url": dataset_manifest_url,
        "release_manifest_url": release_manifest_url,
        "dataset_id": release_dataset_id.strip(),
        "dataset_version": release_version.strip(),
        "package_url": package_url,
        "package_sha_url": package_sha_url,
    }


def resolve_pinned_release(
    *,
    country_iso2: str,
    dataset_manifest_url: str,
    dataset_version: str,
    timeout_sec: int,
    validate_release_manifest_compatibility: Callable[[dict[str, Any]], Any],
) -> dict[str, Any]:
    iso2 = country_iso2.strip().upper()
    version = dataset_version.strip()
    if not version:
        raise ValueError("CADIS_DATASET_VERSION must be non-empty when set.")

    dataset_id = f"{iso2.lower()}.admin"
    release_manifest_rel = f"releases/{iso2}/{dataset_id}/{version}/dataset_release_manifest.json"
    release_manifest_url = repo_relative_url(dataset_manifest_url, release_manifest_rel)
    release_manifest = read_json_url(release_manifest_url, timeout_sec=timeout_sec)

    manifest_country = str(release_manifest.get("country_iso", "")).strip().upper()
    if manifest_country != iso2:
        raise ValueError(
            f"Release manifest country mismatch: expected={iso2} actual={manifest_country!r}."
        )
    release_dataset_id = release_manifest.get("dataset_id")
    release_version = release_manifest.get("dataset_version")
    if not isinstance(release_dataset_id, str) or not release_dataset_id.strip():
        raise ValueError("Release manifest missing dataset_id.")
    if not isinstance(release_version, str) or not release_version.strip():
        raise ValueError("Release manifest missing dataset_version.")
    if release_version.strip() != version:
        raise ValueError(
            f"Pinned release mismatch: requested={version!r} manifest={release_version!r}."
        )

    validate_release_manifest_compatibility(release_manifest)
    base_release_url = release_manifest_url.rsplit("/", 1)[0] + "/"
    package_url = urljoin(base_release_url, "dataset_package.tar.gz")
    package_sha_url = urljoin(base_release_url, "dataset_package.tar.gz.sha256")

    return {
        "country_iso2": iso2,
        "dataset_manifest_url": dataset_manifest_url,
        "release_manifest_url": release_manifest_url,
        "dataset_id": release_dataset_id.strip(),
        "dataset_version": release_version.strip(),
        "package_url": package_url,
        "package_sha_url": package_sha_url,
    }


def download_and_extract_release(
    *,
    cache_root: Path,
    release: dict[str, Any],
    timeout_sec: int,
    validate_dataset_dir: Callable[[Path], None],
    required_files: tuple[str, ...] = DEFAULT_REQUIRED_FILES,
    download_progress: Callable[[str, int, int | None], None] | None = None,
) -> dict[str, Any]:
    target_dir = (
        cache_root
        / release["country_iso2"]
        / release["dataset_id"]
        / release["dataset_version"]
    )
    target_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="cadis_pkg_") as tmp:
        tmp_path = Path(tmp)
        archive_path = tmp_path / "dataset_package.tar.gz"
        package_url = str(release["package_url"])
        archive_path.write_bytes(
            read_bytes_url(
                package_url,
                timeout_sec=timeout_sec,
                progress=(
                    (lambda downloaded, total: download_progress(package_url, downloaded, total))
                    if download_progress is not None
                    else None
                ),
            )
        )

        expected_sha = parse_sha256_file(
            read_text_url(release["package_sha_url"], timeout_sec=timeout_sec)
        )
        actual_sha = sha256_file(archive_path)
        if actual_sha != expected_sha:
            raise ValueError(f"Package checksum mismatch: expected={expected_sha} actual={actual_sha}")

        safe_extract_tar_gz(archive_path, target_dir)

    missing = required_files_present(target_dir, required_files=required_files)
    if missing:
        raise ValueError(f"Extracted package missing required files: {missing}")
    validate_dataset_dir(target_dir)

    return {
        **release,
        "dataset_dir": str(target_dir),
        "used_cached_dataset": False,
        "update_checked": True,
    }


def install_dataset(
    *,
    iso2: str,
    cache_root: str | Path,
    dataset_manifest_url: str = DEFAULT_DATASET_MANIFEST_URL,
    timeout_sec: int = 30,
    update_to_latest: bool = False,
    dataset_version: str | None = None,
    force_reinstall: bool = False,
    validate_release_manifest_compatibility: Callable[[dict[str, Any]], Any] | None = None,
    validate_dataset_dir: Callable[[Path], None] | None = None,
    required_files: tuple[str, ...] = DEFAULT_REQUIRED_FILES,
    download_progress: Callable[[str, int, int | None], None] | None = None,
) -> dict[str, Any]:
    iso2 = iso2.strip().upper()
    if len(iso2) != 2:
        raise ValueError("iso2 must be a 2-letter ISO2 code.")

    cache_root = Path(cache_root).expanduser()
    dataset_id = f"{iso2.lower()}.admin"
    pinned_version = dataset_version.strip() if isinstance(dataset_version, str) else ""
    release_compatibility_validator = (
        validate_release_manifest_compatibility
        if validate_release_manifest_compatibility is not None
        else _noop_validate_manifest
    )
    dataset_validator = validate_dataset_dir if validate_dataset_dir is not None else _noop_validate_dataset_dir

    if pinned_version:
        pinned_dir = cache_root / iso2 / dataset_id / pinned_version
        if (
            pinned_dir.exists()
            and not force_reinstall
            and validate_cached_dataset_dir(
            pinned_dir,
            validate_dataset_dir=dataset_validator,
            required_files=required_files,
            )
        ):
            return {
                "country_iso2": iso2,
                "dataset_id": dataset_id,
                "dataset_version": pinned_version,
                "dataset_dir": str(pinned_dir),
                "used_cached_dataset": True,
                "dataset_manifest_url": dataset_manifest_url,
                "update_checked": False,
                "version_pinned": True,
            }

        release = resolve_pinned_release(
            country_iso2=iso2,
            dataset_manifest_url=dataset_manifest_url,
            dataset_version=pinned_version,
            timeout_sec=timeout_sec,
            validate_release_manifest_compatibility=release_compatibility_validator,
        )
        if force_reinstall and pinned_dir.exists():
            shutil.rmtree(pinned_dir)
        downloaded = download_and_extract_release(
            cache_root=cache_root,
            release=release,
            timeout_sec=timeout_sec,
            validate_dataset_dir=dataset_validator,
            required_files=required_files,
            download_progress=download_progress,
        )
        downloaded["version_pinned"] = True
        return downloaded

    cached = find_local_cached_dataset(
        iso2=iso2,
        cache_root=cache_root,
        dataset_id=dataset_id,
        validate_dataset_dir=dataset_validator,
        required_files=required_files,
    )

    if cached and not update_to_latest and not force_reinstall:
        return {
            **cached,
            "dataset_manifest_url": dataset_manifest_url,
            "update_checked": False,
        }
    if cached and not update_to_latest and force_reinstall:
        pinned_version = str(cached["dataset_version"])
        release = resolve_pinned_release(
            country_iso2=iso2,
            dataset_manifest_url=dataset_manifest_url,
            dataset_version=pinned_version,
            timeout_sec=timeout_sec,
            validate_release_manifest_compatibility=release_compatibility_validator,
        )
        pinned_target = cache_root / iso2 / release["dataset_id"] / release["dataset_version"]
        if pinned_target.exists():
            shutil.rmtree(pinned_target)
        downloaded = download_and_extract_release(
            cache_root=cache_root,
            release=release,
            timeout_sec=timeout_sec,
            validate_dataset_dir=dataset_validator,
            required_files=required_files,
            download_progress=download_progress,
        )
        downloaded["version_pinned"] = True
        return downloaded

    release = resolve_latest_release(
        country_iso2=iso2,
        dataset_manifest_url=dataset_manifest_url,
        timeout_sec=timeout_sec,
        validate_release_manifest_compatibility=release_compatibility_validator,
    )
    latest_target = cache_root / iso2 / release["dataset_id"] / release["dataset_version"]
    if latest_target.exists() and not force_reinstall and validate_cached_dataset_dir(
        latest_target,
        validate_dataset_dir=dataset_validator,
        required_files=required_files,
    ):
        return {
            **release,
            "dataset_dir": str(latest_target),
            "used_cached_dataset": True,
            "update_checked": True,
        }
    if force_reinstall and latest_target.exists():
        shutil.rmtree(latest_target)

    return download_and_extract_release(
        cache_root=cache_root,
        release=release,
        timeout_sec=timeout_sec,
        validate_dataset_dir=dataset_validator,
        required_files=required_files,
        download_progress=download_progress,
    )


def list_available_datasets(
    *,
    dataset_manifest_url: str = DEFAULT_DATASET_MANIFEST_URL,
    timeout_sec: int = 30,
) -> list[dict[str, str]]:
    root_manifest = read_json_url(dataset_manifest_url, timeout_sec=timeout_sec)
    countries = root_manifest.get("countries")
    if not isinstance(countries, dict):
        raise ValueError("dataset_manifest.json missing countries object.")

    out: list[dict[str, str]] = []
    for raw_iso2, country_block in countries.items():
        if not isinstance(raw_iso2, str):
            continue
        if not isinstance(country_block, dict):
            continue
        iso2 = raw_iso2.strip().upper()
        dataset_id = f"{iso2.lower()}.admin"
        release_entry = country_block.get(dataset_id)
        if not isinstance(release_entry, dict):
            continue
        latest = release_entry.get("latest")
        manifest_rel = release_entry.get("manifest")
        if not isinstance(latest, str) or not latest.strip():
            continue
        if not isinstance(manifest_rel, str) or not manifest_rel.strip():
            continue
        out.append(
            {
                "iso2": iso2,
                "dataset_id": dataset_id,
                "latest_version": latest.strip(),
                "manifest": manifest_rel.strip(),
            }
        )
    out.sort(key=lambda item: item["iso2"])
    return out


def bootstrap_release_dataset(
    dataset_base: str,
    country: str,
    *,
    runtime_version: str,
    validate_dataset_dir: Callable[[Path], Any],
    cache_dir: str | Path | None = None,
    timeout_sec: int = 15,
    manifest_name: str = DEFAULT_MANIFEST_NAME,
    manifest_profile: str = DEFAULT_MANIFEST_PROFILE,
    runtime_policy_file: str = DEFAULT_RUNTIME_POLICY_FILE,
    download_progress: Callable[[str, int, int | None], None] | None = None,
) -> dict[str, Any]:
    """
    Download + verify release-manifest governed dataset into local cache.
    """
    iso2 = country.strip().upper()
    if not iso2:
        raise ValueError("country must be a non-empty ISO2 code")

    dataset_url = dataset_base.rstrip("/")
    manifest_url = f"{dataset_url}/{manifest_name}"
    cache_root = Path(cache_dir).expanduser() if cache_dir else (Path.home() / ".cache" / "cadis")

    manifest = read_json_url(manifest_url, timeout_sec=timeout_sec)
    if manifest.get("profile") != manifest_profile:
        raise ValueError(f"Invalid manifest profile: {manifest.get('profile')!r}")
    if manifest.get("schema_version") != 2:
        raise ValueError(f"Unsupported schema version: {manifest.get('schema_version')!r}")
    manifest_country = manifest.get("country_iso")
    if not isinstance(manifest_country, str) or manifest_country.strip().upper() != iso2:
        raise ValueError(
            f"Manifest country mismatch: expected={iso2} actual={manifest.get('country_iso')!r}"
        )
    dataset_id = manifest.get("dataset_id")
    if not isinstance(dataset_id, str) or not dataset_id.strip():
        raise ValueError("Manifest missing dataset_id.")
    dataset_version = manifest.get("dataset_version")
    if not isinstance(dataset_version, str) or not dataset_version.strip():
        raise ValueError("Manifest missing dataset_version.")
    if manifest.get("checksum_algo") != "sha256":
        raise ValueError(f"Unsupported checksum algorithm: {manifest.get('checksum_algo')!r}")

    min_cadis_version, max_cadis_version_exclusive = validate_manifest_runtime_compatibility(
        manifest,
        runtime_version=runtime_version,
    )

    target_dir = cache_root / iso2 / dataset_id.strip() / dataset_version.strip()
    target_dir.mkdir(parents=True, exist_ok=True)

    checksums = manifest.get("checksums")
    if not isinstance(checksums, dict):
        raise ValueError("Manifest missing checksums object.")
    files = checksums.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Manifest checksums.files must be a non-empty object")
    if runtime_policy_file not in files:
        raise ValueError(f"Manifest files must include {runtime_policy_file}.")
    runtime_policy_entry = files[runtime_policy_file]
    if not isinstance(runtime_policy_entry, dict):
        raise ValueError(f"Manifest checksums.files.{runtime_policy_file} must be an object.")
    runtime_policy_checksum = runtime_policy_entry.get("sha256")
    if not isinstance(runtime_policy_checksum, str) or not runtime_policy_checksum.strip():
        raise ValueError(f"Manifest checksums.files.{runtime_policy_file} missing sha256.")

    verified: dict[str, str] = {}
    downloaded: list[str] = []
    for rel, entry in files.items():
        if not isinstance(entry, dict):
            raise ValueError(f"Manifest checksums.files[{rel!r}] must be an object.")
        expected_sha = entry.get("sha256")
        expected_size = entry.get("size")
        if not isinstance(expected_sha, str) or not expected_sha.strip():
            raise ValueError(f"Manifest checksums.files[{rel!r}] missing sha256.")
        if not isinstance(expected_size, int):
            raise ValueError(f"Manifest checksums.files[{rel!r}] missing integer size.")

        url = f"{dataset_url}/{rel}"
        out = target_dir / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(
            read_bytes_url(
                url,
                timeout_sec=timeout_sec,
                progress=(
                    (lambda downloaded, total: download_progress(url, downloaded, total))
                    if download_progress is not None
                    else None
                ),
            )
        )

        actual_sha = sha256_file(out)
        if actual_sha != expected_sha:
            raise ValueError(f"Checksum mismatch for {rel}: expected={expected_sha} actual={actual_sha}")
        if out.stat().st_size != expected_size:
            raise ValueError(f"Size mismatch for {rel}: expected={expected_size} actual={out.stat().st_size}")

        verified[rel] = actual_sha
        downloaded.append(url)

    expected_bundle = manifest.get("manifest_bundle_checksum") or manifest.get("bundle_checksum")
    if expected_bundle:
        actual_bundle = bundle_checksum_from_files(verified)
        if actual_bundle != expected_bundle:
            raise ValueError(
                f"Bundle checksum mismatch: expected={expected_bundle} actual={actual_bundle}"
            )

    runtime_policy_path = target_dir / runtime_policy_file
    if not runtime_policy_path.exists():
        raise ValueError(f"{runtime_policy_file} missing after bootstrap download.")
    actual_policy_sha = sha256_file(runtime_policy_path)
    if actual_policy_sha != runtime_policy_checksum:
        raise ValueError(
            f"{runtime_policy_file} checksum mismatch: "
            f"expected={runtime_policy_checksum} actual={actual_policy_sha}"
        )
    validate_dataset_dir(target_dir)

    local_manifest = target_dir / manifest_name
    local_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "country": iso2,
        "dataset_url": dataset_url,
        "manifest_url": manifest_url,
        "cache_dir": str(target_dir),
        "min_cadis_version": min_cadis_version,
        "max_cadis_version_exclusive": max_cadis_version_exclusive,
        "downloaded_urls": downloaded,
        "manifest": manifest,
    }
