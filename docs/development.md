# Development

```bash
python3 -m unittest discover -s tests -v   # no gateway or network needed
python3 -m ruff check guardian tests
python3 -m mypy
docker build -t qkt-guardrails:dev .
```

`mypy --strict` and `ruff` are clean; CI runs the same checks plus a Docker smoke test. The
ladder (`guardian/ladder.py`) is pure and takes `now`, `equity` and news windows as arguments;
every behaviour change needs a test in `tests/test_ladder.py` before it needs a drill.

Deployments pin a **version tag**, never `latest`. The running guardian logs its version on
startup (`guardian[<name>] v0.5.0 up: ...`) and `python -m guardian --version` prints it. The
release procedure is in [RELEASING.md](RELEASING.md); the change log is
[../CHANGELOG.md](../CHANGELOG.md).

## Try it without a broker

`examples/fake-gateway.py` stands in for mt5-gateway and reads equity from a file, so you can
move an account by hand and watch the ladder fire. The quick start in the README uses it with
`examples/demo.yaml`.

## Status

Acceptance-drilled 2026-08-31: live fill and kill/flatten round trip, SOFT/HARD/STATIC
threshold drills, restart recovery, news feed live. Restructured into a tested package with
typed YAML config in 2026-09. v0.2.0 (2026-09-04) was the first release deployed on the live
prop account. Battle scars land in `CHANGELOG.md` as they are paid for. Drill records are in
[../drills/PLAYBOOK.md](../drills/PLAYBOOK.md).
