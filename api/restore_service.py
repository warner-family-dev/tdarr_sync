import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests

from . import db
from .schemas import to_iso
from .settings import settings


logger = logging.getLogger("tdarr_sync.restore")


class RestoreError(Exception):
    """Base error for restore operations."""


class RestoreAuthError(RestoreError):
    """Raised when the supplied password is invalid."""


class RestoreSelectionError(RestoreError):
    """Raised when the selection expression cannot be resolved."""


class RestoreConfigurationError(RestoreError):
    """Raised when environment configuration is incomplete."""


class RestoreNotFoundError(RestoreError):
    """Raised when a referenced series cannot be resolved."""


@dataclass
class RestoreConfig:
    base_dir: Path
    archive_dir: Path
    backup_suffix: str
    rename_originals: bool
    move_originals: bool
    state_db_file: Path
    tdarr_output_dir: Path
    sonarr_url: str
    sonarr_api_key: str
    sonarr_tag_name: Optional[str]
    sonarr_base_path: Path
    local_mount_base_path: Path
    admin_password: str
    tz_zone = settings.zoneinfo


@dataclass
class SeriesEntry:
    index: int
    series_id: int
    title: str
    processed: int
    total: int
    status: str
    last_processed_at: Optional[int]
    last_processed_at_iso: Optional[str]


@dataclass
class SeriesOutcome:
    series_id: int
    title: str
    restored: List[str] = field(default_factory=list)
    archived_transcodes: List[str] = field(default_factory=list)
    skipped_missing_db: List[str] = field(default_factory=list)
    skipped_missing_archive: List[str] = field(default_factory=list)
    skipped_outside_library: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    _db_paths_to_remove: List[str] = field(default_factory=list, repr=False)


@dataclass
class RestoreOutcome:
    series_requested: int
    series_processed: int
    files_restored: int
    files_skipped_missing_db: int
    files_skipped_missing_archive: int
    results: List[SeriesOutcome]
    messages: List[str] = field(default_factory=list)


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def parse_selection(expression: str, max_index: int) -> List[int]:
    if max_index <= 0:
        raise RestoreSelectionError("There are no series available to select.")

    expr = (expression or "").strip().lower()
    if not expr:
        raise RestoreSelectionError("Selection is required.")

    if expr in {"all", "a", "*"}:
        return list(range(1, max_index + 1))

    selected: List[int] = []
    for raw_part in expr.split(","):
        part = raw_part.strip()
        if not part:
            continue
        if "-" in part:
            bounds = [token.strip() for token in part.split("-", 1)]
            if len(bounds) != 2 or not bounds[0].isdigit() or not bounds[1].isdigit():
                raise RestoreSelectionError(f"Invalid range '{raw_part}' in selection.")
            start = int(bounds[0])
            end = int(bounds[1])
            if start < 1 or end < 1 or start > end:
                raise RestoreSelectionError(f"Invalid range '{raw_part}' in selection.")
            if end > max_index:
                raise RestoreSelectionError(f"Range '{raw_part}' exceeds available series ({max_index}).")
            selected.extend(range(start, end + 1))
            continue
        if not part.isdigit():
            raise RestoreSelectionError(f"Invalid token '{raw_part}' in selection.")
        idx = int(part)
        if idx < 1 or idx > max_index:
            raise RestoreSelectionError(f"Selection index '{idx}' is out of range (1-{max_index}).")
        selected.append(idx)

    unique: List[int] = []
    seen = set()
    for idx in selected:
        if idx not in seen:
            seen.add(idx)
            unique.append(idx)

    if not unique:
        raise RestoreSelectionError("Selection did not resolve to any series.")
    return unique


class RestoreService:
    def __init__(self):
        self.config = self._load_config()
        self._base_dir_resolved = self.config.base_dir.resolve()

    def _load_config(self) -> RestoreConfig:
        try:
            base_dir = Path(os.environ["BASE_DIR"])
            sonarr_url = os.environ["SONARR_URL"]
            sonarr_api_key = os.environ["SONARR_API_KEY"]
        except KeyError as exc:
            raise RestoreConfigurationError(f"Missing required environment variable: {exc}") from exc

        archive_dir = Path(os.getenv("MOVE_ORIGINAL_FILES_DEST", "/media/archive"))
        backup_suffix = os.getenv("BACKUP_SUFFIX", ".orig")
        move_originals = _bool_env("MOVE_ORIGINAL_FILES", True)
        rename_originals = _bool_env("RENAME_ORIGINAL_FILES", True)
        tdarr_output_dir = Path(os.getenv("TDARR_OUTPUT_DIR", "/media/tdarr/output"))
        sonarr_tag_name = os.getenv("SONARR_TAG_NAME") or None
        sonarr_base_path = Path(os.getenv("SONARR_BASE_PATH", "/tv"))
        local_mount_base_path = Path(os.getenv("LOCAL_MOUNT_BASE_PATH", "/mnt/media-videos"))
        admin_password = os.getenv("RESTORE_ADMIN_PASSWORD")

        if not admin_password:
            raise RestoreConfigurationError("RESTORE_ADMIN_PASSWORD is not set in the environment.")

        return RestoreConfig(
            base_dir=base_dir,
            archive_dir=archive_dir,
            backup_suffix=backup_suffix,
            rename_originals=rename_originals,
            move_originals=move_originals,
            state_db_file=settings.state_db_file,
            tdarr_output_dir=tdarr_output_dir,
            sonarr_url=sonarr_url,
            sonarr_api_key=sonarr_api_key,
            sonarr_tag_name=sonarr_tag_name,
            sonarr_base_path=sonarr_base_path,
            local_mount_base_path=local_mount_base_path,
            admin_password=admin_password,
        )

    def _load_processed_map(self) -> Dict[str, Optional[int]]:
        if not self.config.state_db_file.exists():
            raise RestoreError(f"State database not found at {self.config.state_db_file}")
        return db.fetch_all_processed(self.config.state_db_file)

    def series_catalog(self) -> List[SeriesEntry]:
        processed_map = self._load_processed_map()
        series_list = self._fetch_series_list()
        entries: List[SeriesEntry] = []
        for series in series_list:
            processed, total, last_ts = self._series_status(series, processed_map)
            if total == 0:
                status = "none"
            elif processed >= total:
                status = "full"
            elif processed > 0:
                status = "partial"
            else:
                status = "none"
            entries.append(
                SeriesEntry(
                    index=0,
                    series_id=int(series.get("id")),
                    title=str(series.get("title") or "<untitled>"),
                    processed=processed,
                    total=total,
                    last_processed_at=last_ts,
                    last_processed_at_iso=to_iso(last_ts, self.config.tz_zone),
                    status=status,
                )
            )

        status_rank = {"full": 0, "partial": 1, "none": 2}
        entries.sort(key=lambda item: (status_rank.get(item.status, 3), item.title.lower()))

        for idx, entry in enumerate(entries, start=1):
            entry.index = idx
        return entries

    def restore(self, selection: str, password: str) -> RestoreOutcome:
        if password != self.config.admin_password:
            raise RestoreAuthError("Invalid password.")

        processed_map = self._load_processed_map()
        series_list = self._fetch_series_list()
        entries = self._build_entries(series_list, processed_map)

        indexes = parse_selection(selection, len(entries))
        selected_entries = [entries[idx - 1] for idx in indexes]
        if not selected_entries:
            raise RestoreSelectionError("No series matched the selection.")

        outcomes: List[SeriesOutcome] = []
        total_restored = 0
        total_missing_db = 0
        total_missing_archive = 0

        for entry in selected_entries:
            series_outcome = self._restore_single_series(entry, processed_map)
            outcomes.append(series_outcome)
            total_restored += len(series_outcome.restored)
            total_missing_db += len(series_outcome.skipped_missing_db)
            total_missing_archive += len(series_outcome.skipped_missing_archive)

        to_remove: List[str] = []
        for result in outcomes:
            to_remove.extend(result._db_paths_to_remove)

        if to_remove:
            removed = db.delete_processed_entries(self.config.state_db_file, to_remove)
            logger.info("Removed %s processed entries from DB.", removed)

        messages = []
        for outcome in outcomes:
            if outcome.restored:
                messages.append(f"Restored {len(outcome.restored)} files for '{outcome.title}'.")
            elif outcome.errors:
                messages.append(f"No files restored for '{outcome.title}'. See errors.")
            else:
                messages.append(f"No matching files to restore for '{outcome.title}'.")

        return RestoreOutcome(
            series_requested=len(selected_entries),
            series_processed=sum(1 for o in outcomes if o.restored),
            files_restored=total_restored,
            files_skipped_missing_db=total_missing_db,
            files_skipped_missing_archive=total_missing_archive,
            results=outcomes,
            messages=messages,
        )

    def _build_entries(self, series_list, processed_map) -> List[SeriesEntry]:
        entries: List[SeriesEntry] = []
        for series in series_list:
            processed, total, last_ts = self._series_status(series, processed_map)
            status = "none"
            if total > 0:
                if processed >= total:
                    status = "full"
                elif processed > 0:
                    status = "partial"
            entries.append(
                SeriesEntry(
                    index=0,
                    series_id=int(series.get("id")),
                    title=str(series.get("title") or "<untitled>"),
                    processed=processed,
                    total=total,
                    last_processed_at=last_ts,
                    last_processed_at_iso=to_iso(last_ts, self.config.tz_zone),
                    status=status,
                )
            )

        status_rank = {"full": 0, "partial": 1, "none": 2}
        entries.sort(key=lambda item: (status_rank.get(item.status, 3), item.title.lower()))
        for idx, entry in enumerate(entries, start=1):
            entry.index = idx
        return entries

    def _restore_single_series(self, entry: SeriesEntry, processed_map: Dict[str, Optional[int]]) -> SeriesOutcome:
        logger.info("Attempting restore for series '%s' (id=%s)", entry.title, entry.series_id)
        outcome = SeriesOutcome(series_id=entry.series_id, title=entry.title)
        seen_paths: set[str] = set()
        episodes = self._fetch_episode_files(entry.series_id)

        for episode in episodes:
            path = episode.get("path") or episode.get("relativePath")
            if not path:
                continue

            translated = self._translate_path(path)
            resolved = self._resolve_under_base(translated)
            if resolved is None:
                outcome.skipped_outside_library.append(str(translated))
                continue

            abs_str = str(resolved)
            if abs_str in seen_paths:
                continue
            seen_paths.add(abs_str)

            if abs_str not in processed_map or processed_map[abs_str] is None:
                outcome.skipped_missing_db.append(abs_str)
                continue

            archive_candidate = self._select_archive_candidate(resolved)
            if archive_candidate is None:
                outcome.skipped_missing_archive.append(abs_str)
                continue

            backup_transcoded = self._archive_transcoded_file(resolved)

            try:
                resolved.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(archive_candidate), str(resolved))
                outcome.restored.append(abs_str)
                if backup_transcoded:
                    outcome.archived_transcodes.append(str(backup_transcoded))
                outcome._db_paths_to_remove.append(abs_str)
                logger.info("Restored original %s from %s", abs_str, archive_candidate)
            except Exception as exc:
                outcome.errors.append(f"Failed to restore {abs_str}: {exc}")
                logger.error("Failed to restore %s: %s", abs_str, exc)
                if backup_transcoded and not resolved.exists():
                    try:
                        shutil.move(str(backup_transcoded), str(resolved))
                    except Exception as restore_exc:  # pragma: no cover
                        logger.warning("Failed to roll back transcoded file for %s: %s", abs_str, restore_exc)

        return outcome

    def _resolve_under_base(self, candidate: Path) -> Optional[Path]:
        try:
            resolved = candidate if candidate.is_absolute() else self.config.base_dir.joinpath(candidate)
            resolved = resolved.resolve(strict=False)
        except Exception:
            return None
        try:
            resolved.relative_to(self._base_dir_resolved)
        except ValueError:
            return None
        return resolved

    def _translate_path(self, sonarr_path: str) -> Path:
        path = Path(sonarr_path)
        try:
            base_parts = self.config.sonarr_base_path.parts
            if path.is_absolute() and path.parts[: len(base_parts)] == base_parts:
                relative = path.relative_to(self.config.sonarr_base_path)
                return self.config.local_mount_base_path.joinpath(relative)
        except Exception:
            pass
        return path

    def _select_archive_candidate(self, target_path: Path) -> Optional[Path]:
        if not self.config.rename_originals:
            return None

        candidates: List[Path] = []
        if self.config.move_originals:
            try:
                relative = target_path.relative_to(self._base_dir_resolved)
            except ValueError:
                return None
            base_dir = self.config.archive_dir.joinpath(relative.parent)
        else:
            base_dir = target_path.parent

        if not base_dir.exists():
            return None

        for item in base_dir.iterdir():
            name = item.name
            if not name.endswith(self.config.backup_suffix):
                continue
            if not name.startswith(target_path.name):
                continue
            candidates.append(item)

        if not candidates:
            return None

        candidates.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        return candidates[0]

    def _archive_transcoded_file(self, target_path: Path) -> Optional[Path]:
        if not target_path.exists():
            return None

        try:
            relative = target_path.relative_to(self._base_dir_resolved)
            archive_root = self.config.archive_dir.joinpath("_restored_transcodes", relative.parent)
            archive_root.mkdir(parents=True, exist_ok=True)
            destination = archive_root.joinpath(target_path.name)
            destination = self._unique_path(destination)
            shutil.move(str(target_path), str(destination))
            return destination
        except Exception as exc:
            logger.warning("Failed to archive transcoded file for %s: %s", target_path, exc)
            fallback = target_path.with_name(f"{target_path.name}.tdarr")
            fallback = self._unique_path(fallback)
            try:
                shutil.move(str(target_path), str(fallback))
                return fallback
            except Exception as fallback_exc:  # pragma: no cover
                logger.error("Failed to move transcoded file for %s: %s", target_path, fallback_exc)
                return None

    @staticmethod
    def _unique_path(path: Path) -> Path:
        if not path.exists():
            return path
        stem = path.stem
        suffix = path.suffix
        counter = 1
        while True:
            candidate = path.with_name(f"{stem}.{counter}{suffix}")
            if not candidate.exists():
                return candidate
            counter += 1

    def _series_status(self, series: dict, processed_map: Dict[str, Optional[int]]) -> Tuple[int, int, Optional[int]]:
        series_id = int(series.get("id"))
        episodes = self._fetch_episode_files(series_id)
        processed = 0
        total = 0
        last_ts: Optional[int] = None

        for episode in episodes:
            path = episode.get("path") or episode.get("relativePath")
            if not path:
                continue
            translated = self._translate_path(path)
            resolved = self._resolve_under_base(translated)
            if resolved is None:
                continue
            abs_str = str(resolved)
            total += 1
            ts = processed_map.get(abs_str)
            if ts is not None:
                processed += 1
                if ts and (last_ts or 0) < ts:
                    last_ts = ts
        return processed, total, last_ts

    def _fetch_series_list(self) -> List[dict]:
        tag_id = self._find_tag_id()
        try:
            series = self._sonarr_get("/series")
        except RestoreError:
            raise
        if tag_id is None:
            return series
        filtered = []
        for item in series:
            tags = item.get("tags") or []
            if tag_id in tags:
                filtered.append(item)
        return filtered

    def _fetch_episode_files(self, series_id: int) -> List[dict]:
        return self._sonarr_get("/episodefile", params={"seriesId": series_id})

    def _find_tag_id(self) -> Optional[int]:
        if not self.config.sonarr_tag_name:
            return None
        tags = self._sonarr_get("/tag")
        for tag in tags:
            if str(tag.get("label", "")).lower() == self.config.sonarr_tag_name.lower():
                return int(tag.get("id"))
        raise RestoreNotFoundError(
            f"Tag '{self.config.sonarr_tag_name}' not found in Sonarr. Update SONARR_TAG_NAME or add the tag."
        )

    def _sonarr_get(self, endpoint: str, params: Optional[dict] = None):
        url = self.config.sonarr_url.rstrip("/") + "/api/v3" + endpoint
        query = dict(params or {})
        query["apikey"] = self.config.sonarr_api_key
        try:
            response = requests.get(url, params=query, timeout=20)
            response.raise_for_status()
            return response.json()
        except requests.HTTPError as exc:
            raise RestoreError(f"Sonarr request failed ({exc.response.status_code}): {exc}") from exc
        except requests.RequestException as exc:
            raise RestoreError(f"Sonarr request failed: {exc}") from exc
