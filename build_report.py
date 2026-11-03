"""Builds the combined outputs/report.html from both scenario result files.
Run:  uv run python build_report.py   (after run_pipeline.py for both scenarios)"""
from pathlib import Path

from mmm.report_combined import write_combined

print("written" if write_combined(Path(__file__).parent / "outputs") else "need results.json and results_smooth.json first")
