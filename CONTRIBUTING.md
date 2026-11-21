# Contributing

Thanks for your interest in improving **ig-follow-privacy**! This guide keeps contributions smooth.

By participating you agree to follow the [Code of Conduct](CODE_OF_CONDUCT.md).

## 🔒 Security first

- **Never** paste a real `sessionid`, `Authorization` header or cookie into an issue, PR, log or test.
  Use fake values such as `12345678:AbCdEf123456:27:AYhxyz`.
- Tests must never contact Instagram. Use the fakes in `tests/conftest.py` and monkeypatch `input`/`getpass` for the menu.
- If you find a vulnerability that exposes user credentials, please do **not** open a public issue;
  contact the maintainer privately (see the README contact section).

## Development setup

```bash
git clone https://github.com/seuv/instagram-follow-hide.git
cd ig-follow-privacy
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Before you open a pull request

```bash
ruff check .          # lint (add --fix for safe automatic fixes)
ruff format .         # format
pytest                # tests
```

CI runs the same commands on Python 3.9, 3.11 and 3.13, so please make sure they pass locally.

## Guidelines

- Keep the tool **a single file** (`privacy.py`) and **dependency-free** (standard library only) unless there is a strong reason.
- Support Python 3.9+: use `from __future__ import annotations`, no `match` statements.
- Add type hints and docstrings for public functions; follow PEP 8 (enforced by ruff, 100 columns).
- Add or update tests for any behaviour change; bug fixes need a regression test.
- Update `README.md`, `README.id.md`, `docs/usage*.md` and `CHANGELOG.md` (under *Unreleased*) when behaviour changes.
- Keep pull requests focused: one logical change per PR.
- Do not weaken existing safety properties (no redirects, no proxies, no retries, secret redaction,
  fixed endpoint, no session value in CLI arguments) without a discussion first.

## Commit messages

Short imperative subject (≤ 72 chars), e.g. `Refuse empty doc id`. Reference issues like `Fixes #12`.

## Reporting bugs and requesting features

Use the issue templates. For bugs include: OS, Python version, the exact command (without secrets),
and the full error text (redact anything sensitive).

## Release checklist (maintainers)

1. Update the version in `pyproject.toml` and `__version__` in `privacy.py`.
2. Move *Unreleased* entries in `CHANGELOG.md` under the new version and date.
3. Tag: `git tag vX.Y.Z && git push --tags`.
