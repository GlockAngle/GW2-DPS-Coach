from pathlib import Path


def test_app_loads_benchmark_report_before_full_prediction_call():
    app_text = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    load_pos = app_text.index('benchmark_report_path = Path(__file__).parent / "data" / "benchmark_dagger.json"')
    call_pos = app_text.index("build_full_benchmark_prediction(")
    assert load_pos < call_pos
    assert "if benchmark_report is None:" in app_text
