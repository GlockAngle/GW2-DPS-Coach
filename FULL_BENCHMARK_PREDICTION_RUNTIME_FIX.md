# Full Benchmark Prediction runtime fix

Fixed the Streamlit crash:

`name 'benchmark_report' is not defined`

The Rotation Replay tab now loads `data/benchmark_dagger.json` before calling `build_full_benchmark_prediction`. A clear missing-file error is shown if the bundled benchmark report is unavailable.

Validation:
- Application and prediction modules compile.
- Full prediction executes against the bundled report.
- 60 tests pass with `PYTHONPATH=.`.
