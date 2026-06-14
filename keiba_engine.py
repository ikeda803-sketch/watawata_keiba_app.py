from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
import io
import sys
from typing import Iterable

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

if str(DATA_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_DIR))

import main as legacy_main  # noqa: E402


CSV_ENCODINGS = ("utf-8-sig", "cp932")
RESULT_CSV_CANDIDATES = (
    DATA_DIR / "daily_race_db.csv",
    DATA_DIR / "database" / "daily_race_db.csv",
    DATA_DIR / "chou_haitou.csv",
)


class MissingInputFilesError(FileNotFoundError):
    def __init__(self, missing_files: Iterable[Path]):
        self.missing_files = [Path(path) for path in missing_files]
        message = "必要なファイルが見つかりません: " + ", ".join(
            str(path) for path in self.missing_files
        )
        super().__init__(message)


def _has_csv_files(directory: Path) -> bool:
    return directory.exists() and any(directory.rglob("*.csv"))


def find_missing_csv_files(recalc_predict_score: bool = False) -> list[Path]:
    missing: list[Path] = []

    database_dir = DATA_DIR / "database"

    if not _has_csv_files(database_dir):
        missing.append(database_dir / "*.csv")

    return missing


def check_required_files(recalc_predict_score: bool = False) -> None:
    missing = find_missing_csv_files(recalc_predict_score=recalc_predict_score)
    if missing:
        raise MissingInputFilesError(missing)


def _rows_to_dataframe(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    preferred_columns = [
        "date",
        "place",
        "race",
        "horse_number",
        "horse",
        "rank",
        "score",
        "finish",
        "win_return",
        "_saved_prediction",
    ]
    columns = [col for col in preferred_columns if col in df.columns]
    columns.extend(col for col in df.columns if col not in columns)
    df = df.loc[:, columns]

    if "date" in df.columns:
        latest_date = df["date"].dropna().astype(str).max()
        if latest_date:
            df = df[df["date"].astype(str) == latest_date].copy()

    for col in ("race", "rank", "horse_number"):
        if col in df.columns:
            df[f"_{col}_sort"] = pd.to_numeric(df[col], errors="coerce")

    sort_cols = [
        col
        for col in ("place", "_race_sort", "_rank_sort", "_horse_number_sort")
        if col in df.columns
    ]
    if sort_cols:
        df = df.sort_values(sort_cols, kind="stable")

    helper_cols = [col for col in df.columns if col.startswith("_") and col.endswith("_sort")]
    return df.drop(columns=helper_cols)


def _read_csv_with_fallback(path: Path) -> pd.DataFrame:
    for encoding in CSV_ENCODINGS:
        try:
            return pd.read_csv(path, encoding=encoding)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def _latest_generated_csv() -> Path | None:
    candidates = [path for path in RESULT_CSV_CANDIDATES if path.exists()]

    database_dir = DATA_DIR / "database"
    if database_dir.exists():
        candidates.extend(database_dir.rglob("*.csv"))

    if not candidates:
        return None

    return max(candidates, key=lambda path: path.stat().st_mtime)


def _result_dataframe_from_csv() -> pd.DataFrame:
    csv_path = _latest_generated_csv()
    if csv_path is None:
        return pd.DataFrame()

    df = _read_csv_with_fallback(csv_path)
    if df.empty:
        return df

    if "date" in df.columns:
        latest_date = df["date"].dropna().astype(str).max()
        if latest_date:
            df = df[df["date"].astype(str) == latest_date].copy()

    sort_columns = [col for col in ("place", "race", "rank", "horse_number") if col in df.columns]
    for col in ("race", "rank", "horse_number"):
        if col in sort_columns:
            sort_col = f"_{col}_sort"
            df[sort_col] = pd.to_numeric(df[col], errors="coerce")
            sort_columns[sort_columns.index(col)] = sort_col

    if sort_columns:
        df = df.sort_values(sort_columns, kind="stable")

    helper_columns = [col for col in df.columns if col.startswith("_") and col.endswith("_sort")]
    return df.drop(columns=helper_columns)


def run_prediction(
    recalc_predict_score: bool = False,
    run_heavy_reports: bool = False,
) -> pd.DataFrame:
    rows, _logs = run_prediction_with_logs(
        recalc_predict_score=recalc_predict_score,
        run_heavy_reports=run_heavy_reports,
    )
    return rows


def run_prediction_with_logs(
    recalc_predict_score: bool = False,
    run_heavy_reports: bool = False,
) -> tuple[pd.DataFrame, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        legacy_main.main()

    try:
        df = _result_dataframe_from_csv()
    except Exception as exc:
        buffer.write(f"\nCSV読み込みエラー: {exc}\n")
        df = pd.DataFrame()

    return df, buffer.getvalue()
