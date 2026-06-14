from __future__ import annotations

from contextlib import redirect_stdout
from pathlib import Path
import io
import os
import sys
from typing import Iterable

import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"

if str(DATA_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_DIR))

import main as legacy_main  # noqa: E402


CSV_ENCODINGS = ("utf-8-sig", "cp932")


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

    result_csv = Path(legacy_main.RESULT_CSV_FILE)
    database_dir = DATA_DIR / "database"

    if not result_csv.exists():
        missing.append(result_csv)

    if not _has_csv_files(database_dir):
        missing.append(database_dir / "*.csv")

    if recalc_predict_score:
        yoso_data = Path(legacy_main.YOSO_DATA_FILE)
        if not yoso_data.exists():
            missing.append(yoso_data)

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
    check_required_files(recalc_predict_score=recalc_predict_score)

    old_recalc = os.environ.get("RECALC_PREDICT_SCORE")
    old_heavy = os.environ.get("RUN_HEAVY_REPORTS")
    os.environ["RECALC_PREDICT_SCORE"] = "1" if recalc_predict_score else ""
    os.environ["RUN_HEAVY_REPORTS"] = "1" if run_heavy_reports else ""

    buffer = io.StringIO()
    try:
        with redirect_stdout(buffer):
            legacy_main.run_daily_builder()
            legacy_main.cleanup_duplicate_prediction_files()
            data = legacy_main.load_db()

            if recalc_predict_score:
                data = legacy_main.apply_current_predict_scores(data)

            data = legacy_main.apply_roi_odds_calibration(data)
            data = legacy_main.apply_previous_popularity_calibration(data)
            data = legacy_main.rerank_predictions_by_score(data)
            data = legacy_main.apply_saved_prediction_scores(data)

            legacy_main.display_race_results(data)
            legacy_main.analyze_recovery_rate(data)
            legacy_main.analyze_top1_win_rate(data)

            if run_heavy_reports:
                legacy_main.save_performance_summary(data)
                legacy_main.save_win_return_6x_summary(data)
                legacy_main.save_score_and_odds_reports(data)
                legacy_main.save_super_anchor_index_report(data)
                legacy_main.save_top1_odds6_wide_flow_report(data)
                legacy_main.save_trifecta_box_complete_report(data)
                legacy_main.save_rank1_hit_report(data)
                legacy_main.analyze_top1_place_quinella_by_score(data)
                legacy_main.save_rank_score_finish_rates(data)
                legacy_main.save_rank1_hit_monthly_summary(data)
    finally:
        if old_recalc is None:
            os.environ.pop("RECALC_PREDICT_SCORE", None)
        else:
            os.environ["RECALC_PREDICT_SCORE"] = old_recalc

        if old_heavy is None:
            os.environ.pop("RUN_HEAVY_REPORTS", None)
        else:
            os.environ["RUN_HEAVY_REPORTS"] = old_heavy

    return _rows_to_dataframe(data), buffer.getvalue()
