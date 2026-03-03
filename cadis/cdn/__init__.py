"""Dataset lifecycle/provisioning library surface for Cadis."""

from cadis.version import __version__

from cadis.cdn.archive import safe_extract_tar_gz
from cadis.cdn.bootstrap import (
    bootstrap_release_dataset,
    download_and_extract_release,
    find_local_cached_dataset,
    install_dataset,
    list_available_datasets,
    parse_version_for_sort,
    required_files_present,
    resolve_latest_release,
    resolve_pinned_release,
    validate_cached_dataset_dir,
)
from cadis.cdn.hashing import bundle_checksum_from_files, parse_sha256_file, sha256_file
from cadis.cdn.runtime_compat import parse_semver, validate_manifest_runtime_compatibility
from cadis.cdn.transport import read_bytes_url, read_json_url, read_text_url, repo_relative_url

__all__ = [
    "__version__",
    "install_dataset",
    "list_available_datasets",
    "bootstrap_release_dataset",
    "bundle_checksum_from_files",
    "download_and_extract_release",
    "find_local_cached_dataset",
    "parse_version_for_sort",
    "parse_semver",
    "parse_sha256_file",
    "required_files_present",
    "read_bytes_url",
    "read_json_url",
    "read_text_url",
    "repo_relative_url",
    "resolve_latest_release",
    "resolve_pinned_release",
    "safe_extract_tar_gz",
    "sha256_file",
    "validate_manifest_runtime_compatibility",
    "validate_cached_dataset_dir",
]
