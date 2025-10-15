import logging
import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

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
class SeasonEntry:
    number: int
    name: str
    processed: int
    total: int
    status: str
    last_processed_at: Optional[int]
    last_processed_at_iso: Optional[str]


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
    seasons: List[SeasonEntry]


@dataclass
class SeriesOutcome:
    series_id: int
    title: str
    selected_seasons: Optional[List[int]] = None
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
        return self._build_entries(series_list, processed_map)

    def restore(
        self,
        password: str,
        selection_expr: Optional[str] = None,
        structured: Optional[List[Dict[str, Optional[List[int]]]]] = None,
    ) -> RestoreOutcome:
        if password != self.config.admin_password:
            raise RestoreAuthError("Invalid password.")

        if not selection_expr and not structured:
            raise RestoreSelectionError("A selection is required.")

        processed_map = self._load_processed_map()
        series_list = self._fetch_series_list()
        entries = self._build_entries(series_list, processed_map)
        entry_by_id = {entry.series_id: entry for entry in entries}

        selected: List[Tuple[SeriesEntry, Optional[Set[int]]]] = []

        if structured:
            if not isinstance(structured, list) or len(structured) == 0:
                raise RestoreSelectionError("Structured selection must include at least one series.")
            for item in structured:
                series_id_raw = item.get("series_id")
                if series_id_raw is None:
                    raise RestoreSelectionError("Structured selection missing series_id.")
                try:
                    series_id = int(series_id_raw)
                except (TypeError, ValueError) as exc:
                    raise RestoreSelectionError(f"Invalid series_id value: {series_id_raw}") from exc
                entry = entry_by_id.get(series_id)
                if entry is None:
                    raise RestoreNotFoundError(f"Series id {series_id} not found in the current catalog.")

                seasons_raw = item.get("seasons")
                if not seasons_raw:
                    selected.append((entry, None))
                    continue

                try:
                    requested_seasons = {int(value) for value in seasons_raw}
                except (TypeError, ValueError) as exc:
                    raise RestoreSelectionError(f"Invalid season list for series {series_id}.") from exc

                valid_numbers = {season.number for season in entry.seasons}
                invalid = requested_seasons - valid_numbers
                if invalid:
                    raise RestoreSelectionError(
                        f"Series '{entry.title}' does not contain seasons: {sorted(invalid)}"
                    )
                selected.append((entry, requested_seasons))
        else:
            indexes = parse_selection(selection_expr or "", len(entries))
            if not indexes:
                raise RestoreSelectionError("No series matched the selection.")
            selected = [(entries[idx - 1], None) for idx in indexes]

        logger.info(
            "Restore starting (request_id=%s) selections=%d",
            getattr(self, "_current_request_id", "n/a"),
            len(structured or []),
        )
        outcomes: List[SeriesOutcome] = []
        total_restored = 0
        total_missing_db = 0
        total_missing_archive = 0
        any_errors = False
        restore_started = time.monotonic()

        for entry, seasons in selected:
            try:
                logger.info(
                    "Restore starting for series '%s' (id=%s) seasons=%s",
                    entry.title,
                    entry.series_id,
                    sorted(seasons) if seasons else "all",
                )
                series_started = time.monotonic()
                series_outcome = self._restore_single_series(entry, processed_map, seasons)
                logger.info(
                    "Restore finished for series '%s' (id=%s) restored=%d errors=%d duration=%.2fs",
                    entry.title,
                    entry.series_id,
                    len(series_outcome.restored),
                    len(series_outcome.errors),
                    time.monotonic() - series_started,
                )
            except RestoreError as exc:
                logger.error("Restore failed for series '%s' (id=%s): %s", entry.title, entry.series_id, exc)
                series_outcome = SeriesOutcome(
                    series_id=entry.series_id,
                    title=entry.title,
                    selected_seasons=sorted(seasons) if seasons else None,
                    errors=[str(exc)],
                )
                any_errors = True
            except Exception as exc:  # pragma: no cover
                logger.exception("Unexpected error restoring series '%s' (id=%s)", entry.title, entry.series_id)
                series_outcome = SeriesOutcome(
                    series_id=entry.series_id,
                    title=entry.title,
                    selected_seasons=sorted(seasons) if seasons else None,
                    errors=[f"Unexpected error: {exc}"],
                )
                any_errors = True
            outcomes.append(series_outcome)
            total_restored += len(series_outcome.restored)
            total_missing_db += len(series_outcome.skipped_missing_db)
            total_missing_archive += len(series_outcome.skipped_missing_archive)
            if series_outcome.errors:
                any_errors = True

        to_remove: List[str] = []
        for result in outcomes:
            to_remove.extend(result._db_paths_to_remove)

        if to_remove and not any_errors:
            removed = db.delete_processed_entries(self.config.state_db_file, to_remove)
            logger.info("Removed %s processed entries from DB.", removed)
        elif to_remove and any_errors:
            logger.warning(
                "Restore completed with errors; skipping DB cleanup for %d processed entries.", len(to_remove)
            )

        messages = []
        for outcome in outcomes:
            if outcome.restored:
                messages.append(f"Restored {len(outcome.restored)} files for '{outcome.title}'.")
            elif outcome.errors:
                messages.append(f"No files restored for '{outcome.title}'. See errors.")
            else:
                messages.append(f"No matching files to restore for '{outcome.title}'.")

        if any_errors:
            messages.append(
                "One or more series reported errors; processed markers were left intact so you can retry the restore."
            )

        duration = time.monotonic() - restore_started
        logger.info(
            "Restore completed in %.2fs: series_requested=%d series_processed=%d files_restored=%d errors=%s",
            duration,
            len(selected),
            sum(1 for o in outcomes if o.restored),
            total_restored,
            any_errors,
        )

        return RestoreOutcome(
            series_requested=len(selected),
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
            snapshot = self._series_snapshot(series, processed_map)
            entries.append(snapshot)

        status_rank = {"full": 0, "partial": 1, "none": 2}
        entries.sort(key=lambda item: (status_rank.get(item.status, 3), item.title.lower()))
        for idx, entry in enumerate(entries, start=1):
            entry.index = idx
        return entries

    def _series_snapshot(self, series: dict, processed_map: Dict[str, Optional[int]]) -> SeriesEntry:
        series_id = int(series.get("id"))
        title = str(series.get("title") or "<untitled>")
        episodes = self._fetch_episode_files(series_id)

        total = 0
        processed = 0
        last_ts: Optional[int] = None
        season_stats: Dict[int, Dict[str, Optional[int] | int]] = {}

        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            path = episode.get("path") or episode.get("relativePath")
            if not path:
                continue

            translated = self._translate_path(path)
            resolved = self._resolve_under_base(translated)
            if resolved is None:
                continue

            abs_str = str(resolved)
            ts = processed_map.get(abs_str)

            total += 1
            if ts is not None:
                processed += 1
                if ts and (last_ts or 0) < ts:
                    last_ts = ts

            season_number = self._episode_season_number(episode)
            stats = season_stats.setdefault(season_number, {"total": 0, "processed": 0, "last": None})
            stats["total"] = int(stats["total"]) + 1
            if ts is not None:
                stats["processed"] = int(stats["processed"]) + 1
                if ts and (stats["last"] or 0) < ts:
                    stats["last"] = ts

        status = self._status_from_counts(processed, total)
        seasons: List[SeasonEntry] = []
        for number in sorted(season_stats):
            stats = season_stats[number]
            season_processed = int(stats["processed"])  # type: ignore[index]
            season_total = int(stats["total"])  # type: ignore[index]
            season_last_raw = stats["last"]  # type: ignore[index]
            season_last = season_last_raw if isinstance(season_last_raw, int) else None
            seasons.append(
                SeasonEntry(
                    number=number,
                    name=self._season_label(number),
                    processed=season_processed,
                    total=season_total,
                    status=self._status_from_counts(season_processed, season_total),
                    last_processed_at=season_last,
                    last_processed_at_iso=to_iso(season_last, self.config.tz_zone),
                )
            )

        return SeriesEntry(
            index=0,
            series_id=series_id,
            title=title,
            processed=processed,
            total=total,
            status=status,
            last_processed_at=last_ts,
            last_processed_at_iso=to_iso(last_ts, self.config.tz_zone),
            seasons=seasons,
        )

    @staticmethod
    def _season_label(number: int) -> str:
        if number == 0:
            return "Specials"
        return f"Season {number:02d}"

    @staticmethod
    def _status_from_counts(processed: int, total: int) -> str:
        if total <= 0:
            return "none"
        if processed <= 0:
            return "none"
        if processed >= total:
            return "full"
        return "partial"

    @staticmethod
    def _episode_season_number(episode: dict) -> int:
        raw = episode.get("seasonNumber")
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def _restore_single_series(
        self,
        entry: SeriesEntry,
        processed_map: Dict[str, Optional[int]],
        selected_seasons: Optional[Set[int]] = None,
    ) -> SeriesOutcome:
        logger.info("Attempting restore for series '%s' (id=%s)", entry.title, entry.series_id)
        seasons_list = sorted(selected_seasons) if selected_seasons else None
        outcome = SeriesOutcome(series_id=entry.series_id, title=entry.title, selected_seasons=seasons_list)
        seen_paths: set[str] = set()
        episodes = self._fetch_episode_files(entry.series_id)

        for episode in episodes:
            if not isinstance(episode, dict):
                continue
            path = episode.get("path") or episode.get("relativePath")
            if not path:
                continue

            translated = self._translate_path(path)
            resolved = self._resolve_under_base(translated)
            if resolved is None:
                outcome.skipped_outside_library.append(str(translated))
                continue

            season_number = self._episode_season_number(episode)
            if selected_seasons and season_number not in selected_seasons:
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
