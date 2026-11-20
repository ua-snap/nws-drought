import datetime

import numpy as np
import pandas as pd
import pytest
import xarray as xr

import download_helpers
import pipeline_run
from config import SOIL_MOISTURE_WEIGHT_LAYER1, SOIL_MOISTURE_WEIGHT_LAYER2


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setattr(download_helpers, "RECENT_DATA_ROOT", tmp_path)
    monkeypatch.setattr(pipeline_run, "RECENT_DATA_ROOT", tmp_path)
    return tmp_path


def write_month(variable_key, year, month, last_day, short_name, fill=None):
    path = download_helpers.monthly_file_path(variable_key, year, month)
    path.parent.mkdir(parents=True, exist_ok=True)
    times = pd.date_range(f"{year}-{month:02d}-01", periods=last_day, freq="D")
    rng = np.random.default_rng(year * 100 + month)
    data = (
        rng.random((last_day, 2, 3), dtype="float32")
        if fill is None
        else np.full((last_day, 2, 3), fill, dtype="float32")
    )
    xr.Dataset(
        {short_name: (("valid_time", "latitude", "longitude"), data)},
        coords={
            "valid_time": times,
            "latitude": [60.0, 59.9],
            "longitude": [-150.0, -149.9, -149.8],
        },
    ).to_netcdf(path)
    return path


def write_all_swe(analysis_date, skip=None):
    for year, month in download_helpers.coverage_months(analysis_date):
        if (year, month) == skip:
            continue
        last_day = (
            analysis_date.day
            if (year, month) == (analysis_date.year, analysis_date.month)
            else pd.Period(f"{year}-{month:02d}").days_in_month
        )
        write_month("swe", year, month, last_day, "sd")


def test_assembled_dataset_spans_coverage_without_duplicates(root):
    analysis_date = datetime.date(2026, 11, 18)
    write_all_swe(analysis_date)

    ds = pipeline_run.assemble_recent_downloads("swe", analysis_date)

    times = pd.DatetimeIndex(ds.valid_time.values)
    assert times[0] == pd.Timestamp("2025-01-01")
    assert times[-1] == pd.Timestamp("2026-11-18")
    assert times.is_unique
    assert (
        len(times) == (datetime.date(2026, 11, 18) - datetime.date(2025, 1, 1)).days + 1
    )


def test_missing_month_is_named_in_error(root):
    analysis_date = datetime.date(2026, 11, 18)
    write_all_swe(analysis_date, skip=(2026, 3))

    with pytest.raises(FileNotFoundError, match="2026-03"):
        pipeline_run.assemble_recent_downloads("swe", analysis_date)


def test_combined_soil_moisture_is_weighted_sum_of_layers(root):
    analysis_date = datetime.date(2026, 1, 10)
    for year, month in download_helpers.coverage_months(analysis_date):
        last_day = (
            analysis_date.day
            if (year, month) == (analysis_date.year, analysis_date.month)
            else pd.Period(f"{year}-{month:02d}").days_in_month
        )
        write_month("swvl1", year, month, last_day, "swvl1")
        write_month("swvl2", year, month, last_day, "swvl2")
        # distinct values per layer
    pipeline_run.combine_swvl(analysis_date)

    ds = pipeline_run.assemble_recent_downloads("swvl", analysis_date)
    swvl1 = download_helpers_open("swvl1", analysis_date)
    swvl2 = download_helpers_open("swvl2", analysis_date)
    expected = (
        swvl1 * SOIL_MOISTURE_WEIGHT_LAYER1 + swvl2 * SOIL_MOISTURE_WEIGHT_LAYER2
    ).astype("float32")

    assert ds["swvl"].dtype == np.float32
    np.testing.assert_array_equal(ds["swvl"].values, expected.values)
    # January analysis date: still January 1 of the previous year onward
    assert pd.Timestamp(ds.valid_time.values[0]) == pd.Timestamp("2025-01-01")
    assert pd.Timestamp(ds.valid_time.values[-1]) == pd.Timestamp("2026-01-10")


def download_helpers_open(variable_key, analysis_date):
    short = pipeline_run.VARIABLE_REGISTRY[variable_key]["short_name"]
    files = download_helpers.recurring_monthly_files(variable_key, analysis_date)
    return xr.concat([xr.open_dataset(f)[short] for f in files], dim="valid_time")


def test_january_analysis_date_assembles_previous_year_and_january(root):
    analysis_date = datetime.date(2026, 1, 20)
    write_all_swe(analysis_date)

    ds = pipeline_run.assemble_recent_downloads("swe", analysis_date)

    times = pd.DatetimeIndex(ds.valid_time.values)
    assert times[0] == pd.Timestamp("2025-01-01")
    assert times[-1] == pd.Timestamp("2026-01-20")
    assert times.is_unique


def test_summed_variables_are_labeled_by_the_day_they_measure(root, monkeypatch):
    # a recurring file labels each total by its 00:00 reading on the next day;
    # the fake files are netCDF, which the reader handles like the real GRIB
    monkeypatch.setitem(pipeline_run.VARIABLE_REGISTRY["tp"], "suffix", ".nc")
    analysis_date = datetime.date(2026, 3, 10)
    for year, month in download_helpers.coverage_months(analysis_date):
        last_day = (
            analysis_date.day
            if (year, month) == (analysis_date.year, analysis_date.month)
            else pd.Period(f"{year}-{month:02d}").days_in_month
        )
        write_month("tp", year, month, last_day, "tp")
    stored = download_helpers_open("tp", analysis_date)

    ds = pipeline_run.assemble_recent_downloads("tp", analysis_date)

    times = pd.DatetimeIndex(ds.valid_time.values)
    assert times[0] == pd.Timestamp("2024-12-31")
    assert times[-1] == pd.Timestamp("2026-03-09")
    np.testing.assert_array_equal(ds["tp"].values, stored.values)
