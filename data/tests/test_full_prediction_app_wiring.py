from pathlib import Path


def test_simulation_page_runs_real_gw2combat_package():
    app_text = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
    package_pos = app_text.index("package = build_antiquary_benchmark_package()")
    run_pos = app_text.index("result = run_encounter(package.encounter, package.files")
    parse_pos = app_text.index("analysis = analyze_audit(result, source_actor=\"player\")")
    assert package_pos < run_pos < parse_pos
    assert 'key="run_antiquary_benchmark"' in app_text
