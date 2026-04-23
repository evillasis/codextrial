"""
Tests for batch CSV processing and the token-bucket rate limiter.
"""

import csv
import io
import os
import tempfile
import threading
import time

import pytest

from sun_exposure.batch import process_batch, OUTPUT_FIELDNAMES
from sun_exposure.exposure import ExposureCalculator
from sun_exposure.geo._ratelimit import TokenBucketLimiter


FAST_CALC = ExposureCalculator(year=2025, day_step=14)

# ---------------------------------------------------------------------------
# TokenBucketLimiter
# ---------------------------------------------------------------------------

class TestTokenBucketLimiter:
    def test_single_acquire_immediate(self):
        limiter = TokenBucketLimiter(rate=10.0)
        start = time.monotonic()
        limiter.acquire()
        assert time.monotonic() - start < 0.1

    def test_burst_then_rate_limit(self):
        limiter = TokenBucketLimiter(rate=10.0, burst=2.0)
        # First two acquires should be near-instant (burst capacity)
        limiter.acquire()
        limiter.acquire()
        # Third should be throttled
        start = time.monotonic()
        limiter.acquire()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05  # at least some throttle

    def test_thread_safe(self):
        limiter = TokenBucketLimiter(rate=100.0, burst=5.0)
        results = []
        def worker():
            limiter.acquire()
            results.append(True)
        threads = [threading.Thread(target=worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)
        assert len(results) == 5


# ---------------------------------------------------------------------------
# Batch CSV processing
# ---------------------------------------------------------------------------

def _write_csv(rows: list[dict], path: str) -> None:
    fieldnames = rows[0].keys()
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _read_csv(path: str) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


class TestBatchProcessing:
    def test_five_rows_produce_five_output_rows(self, tmp_path):
        rows = [
            {"lat": "40.4168", "lon": "-3.7038", "facade_azimuth": "180", "address": "Madrid S"},
            {"lat": "40.4168", "lon": "-3.7038", "facade_azimuth": "90",  "address": "Madrid E"},
            {"lat": "40.4168", "lon": "-3.7038", "facade_azimuth": "270", "address": "Madrid W"},
            {"lat": "4.711",   "lon": "-74.072",  "facade_azimuth": "180", "address": "Bogota S"},
            {"lat": "4.711",   "lon": "-74.072",  "facade_azimuth": "90",  "address": "Bogota E"},
        ]
        inp = str(tmp_path / "in.csv")
        out = str(tmp_path / "out.csv")
        _write_csv(rows, inp)

        n = process_batch(inp, out, calc=FAST_CALC, max_workers=2)
        assert n == 5
        result_rows = _read_csv(out)
        assert len(result_rows) == 5

    def test_output_has_all_required_fields(self, tmp_path):
        rows = [{"lat": "40.4168", "lon": "-3.7038", "facade_azimuth": "180"}]
        inp = str(tmp_path / "in.csv")
        out = str(tmp_path / "out.csv")
        _write_csv(rows, inp)
        process_batch(inp, out, calc=FAST_CALC)
        result_rows = _read_csv(out)
        assert len(result_rows) == 1
        for field in OUTPUT_FIELDNAMES:
            assert field in result_rows[0]

    def test_valid_rows_have_empty_error_column(self, tmp_path):
        rows = [
            {"lat": "40.4168", "lon": "-3.7038", "facade_azimuth": "180"},
            {"lat": "40.4168", "lon": "-3.7038", "facade_azimuth": "90"},
        ]
        inp = str(tmp_path / "in.csv")
        out = str(tmp_path / "out.csv")
        _write_csv(rows, inp)
        process_batch(inp, out, calc=FAST_CALC)
        result_rows = _read_csv(out)
        assert all(row["error"] == "" for row in result_rows)

    def test_invalid_row_produces_error_not_crash(self, tmp_path):
        # One valid + one invalid (missing both address and lat/lon)
        rows = [
            {"lat": "40.4168", "lon": "-3.7038", "facade_azimuth": "180"},
            {"lat": "",         "lon": "",         "facade_azimuth": "180"},  # no coords, no address
        ]
        inp = str(tmp_path / "in.csv")
        out = str(tmp_path / "out.csv")
        _write_csv(rows, inp)
        n = process_batch(inp, out, calc=FAST_CALC)
        assert n == 2
        result_rows = _read_csv(out)
        assert len(result_rows) == 2
        assert result_rows[0]["error"] == ""
        assert result_rows[1]["error"] != ""

    def test_street_angle_column_expands_to_two_rows(self, tmp_path):
        # street_angle with side="both" → 2 Building objects → 2 output rows
        rows = [{"lat": "40.4168", "lon": "-3.7038", "street_angle": "0", "street_side": "both"}]
        inp = str(tmp_path / "in.csv")
        out = str(tmp_path / "out.csv")
        _write_csv(rows, inp)
        n = process_batch(inp, out, calc=FAST_CALC)
        assert n == 1  # 1 input row
        result_rows = _read_csv(out)
        assert len(result_rows) == 2  # 2 output rows (E + W facades)

    def test_weighted_score_is_positive_for_sun_facing_facade(self, tmp_path):
        rows = [{"lat": "40.4168", "lon": "-3.7038", "facade_azimuth": "180"}]
        inp = str(tmp_path / "in.csv")
        out = str(tmp_path / "out.csv")
        _write_csv(rows, inp)
        process_batch(inp, out, calc=FAST_CALC)
        result_rows = _read_csv(out)
        assert float(result_rows[0]["weighted_score"]) > 0

    def test_cardinal_column_accepted(self, tmp_path):
        rows = [{"lat": "40.4168", "lon": "-3.7038", "cardinal": "S"}]
        inp = str(tmp_path / "in.csv")
        out = str(tmp_path / "out.csv")
        _write_csv(rows, inp)
        process_batch(inp, out, calc=FAST_CALC)
        result_rows = _read_csv(out)
        assert result_rows[0]["facade_azimuth"] == "180.0"
        assert result_rows[0]["error"] == ""
