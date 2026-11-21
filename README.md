# ig-follow-privacy

[![CI](https://github.com/seuv/instagram-follow-hide/actions/workflows/ci.yml/badge.svg)](https://github.com/seuv/instagram-follow-hide/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)

**English**

A **single-file**, dependency-free tool that **hides or unhides the followers/following list** of
your own Instagram account, using your `sessionid` cookie. It has a colored interactive menu and
plain one-shot commands for scripts.

```
   ___ ____   _____ ___  _     _     _____        __
  |_ _/ ___| |  ___/ _ \| |   | |   / _ \ \      / /
   | | |  _  | |_ | | | | |   | |  | | | \ \ /\ / /
   | | |_| | |  _|| |_| | |___| |__| |_| |\ V  V /
  |___\____| |_|   \___/|_____|_____\___/  \_/\_/
  instagram-follow-privacy · hide / unhide followers list v0.1.0
    unofficial · use only on your own account

  14:54:07 · session user id 12345678
  14:54:07 · last action none yet
  ────────────────────────────────────────────
  14:54:07 · 1 · hide followers/following list
  14:54:07 · 2 · unhide followers/following list
  14:54:07 · 3 · preview request (dry run)
  14:54:07 · 4 · change session
  14:54:07 · 5 · exit
  ────────────────────────────────────────────
  › 3

  ────────────────────────────────────────────
  14:54:07 ✓ session · valid · user id 12345678
  14:54:07 · endpoint https://i.instagram.com/graphql/query
  14:54:07 · doc id 2669261950526978627082629536
  14:54:07 · hide sends value=true · unhide sends value=false
  14:54:07 ✓ dry run · no request was sent
  ────────────────────────────────────────────
  › press enter to continue
```

> ## ⚠️ Disclaimer
> This project is **unofficial** and is not affiliated with, endorsed by, or connected to
> Instagram or Meta. It calls an **undocumented** Instagram endpoint, which may change or stop
> working at any time and may be against Instagram's Terms of Use. You use it **at your own risk**.
> Use it only on an account you own. Your `sessionid` gives full access to your account:
> treat it like a password and never share or commit it.

## Features

- **Interactive menu** (run with no arguments): hide, unhide, preview request, change session.
  Colored, timestamped output; colors turn off automatically when piped or when `NO_COLOR` is set.
- **One-shot commands** for scripts: `hide`, `unhide`, with `--dry-run` and `--stdin`.
- Session value comes from a **hidden prompt**, `--stdin` or `IG_SESSIONID`; it is **never** a
  command-line argument and is **never written to disk** (it only lives in memory for the run).
- Secrets are scrubbed from error messages; redirects are refused; proxies are ignored; each
  action sends **one** request and never retries automatically.
- One file (`privacy.py`), standard library only, Python 3.9+.

## Prerequisites

- Python **3.9 or newer** (`python3 --version`)
- Your own Instagram `sessionid` cookie value (see [How to get your sessionid](#how-to-get-your-sessionid))

## Installation

No installation is needed: it is one file.

```bash
git clone https://github.com/seuv/instagram-follow-hide.git
cd ig-follow-privacy
python3 privacy.py
```

Optional, to get an `ig-follow-privacy` command on your PATH:

```bash
python3 -m venv .venv && source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install .
ig-follow-privacy --version
```

## Usage

```bash
# Interactive menu (needs a terminal)
python3 privacy.py

# One-shot commands (the sessionid is asked through a hidden prompt)
python3 privacy.py hide
python3 privacy.py unhide

# Check your session value without sending anything
python3 privacy.py hide --dry-run

# Non-interactive
export IG_SESSIONID='<your sessionid value>'
python3 privacy.py hide --no-banner
printf '%s\n' "$IG_SESSIONID" | python3 privacy.py unhide --stdin
```

(If you installed it with `pip`, replace `python3 privacy.py` with `ig-follow-privacy`.)

Exit codes: `0` success · `1` error (invalid input, network/HTTP failure, not confirmed) ·
`2` bad usage (including the menu without a terminal) · `130` interrupted with Ctrl+C.

Full reference: [docs/usage.md](docs/usage.md).

### Example output

```text
$ python3 privacy.py hide --no-banner
  14:58:01 ✓ session · valid · user id 12345678
  14:58:01 · sending hide request...
  14:58:02 ✓ hidden · lists are now hidden · instagram returned value=true

$ python3 privacy.py unhide --no-banner
  14:58:30 ✓ session · valid · user id 12345678
  14:58:30 · sending unhide request...
  14:58:31 ✓ visible · lists are now visible · instagram returned value=false

$ python3 privacy.py hide --no-banner        # pasted "sessionid=..." by mistake
  14:59:10 ✗ session · Enter only the sessionid cookie value, without 'sessionid='.
```

## How to get your sessionid

1. Log in to [instagram.com](https://www.instagram.com) in a desktop browser.
2. Open the developer tools (F12) → **Application** (Chrome/Edge) or **Storage** (Firefox) → **Cookies** → `https://www.instagram.com`.
3. Copy the **Value** of the cookie named `sessionid`. It starts with your numeric user ID followed by `:` or `%3A`.
4. Paste only the value (not `sessionid=`). Logging out invalidates it.

## Configuration

| Setting | CLI flag | Environment variable | Default |
| --- | --- | --- | --- |
| Session value | *(prompt)* / `--stdin` | `IG_SESSIONID` | – |
| `client_doc_id` | `--doc-id` | `IG_CLIENT_DOC_ID` | `2669261950526978627082629536` |
| `X-IG-App-ID` | `--app-id` | `IG_APP_ID` | `124024574287414` |
| `User-Agent` | `--user-agent` | `IG_USER_AGENT` | `Instagram 453.0.0` |
| Timeout (seconds) | `--timeout` | `IG_TIMEOUT` | `15` |
| Disable colors | – | `NO_COLOR` | – |

The API endpoint is deliberately **not** configurable, so your session cookie can only be sent to
`https://i.instagram.com/graphql/query`. Flags take priority over environment variables.

## Status

- Unit tests cover validation, request construction, response checking, the console output and
  the menu using a **mocked** HTTP layer. They do not contact Instagram.
- `hide` keeps the behaviour of the original script.
- `unhide` sends the same mutation with `value=false` and expects Instagram to answer
  `value=false`. confirm this against a real account before the first release.

## Project structure

```
ig-follow-privacy/
├── privacy.py     the whole tool (client + menu + CLI)
├── tests/                   pytest suite (mocked HTTP)
├── docs/{usage.md,usage.id.md}
├── examples/use_as_library.py
├── .github/                 CI, issue/PR templates, Dependabot
├── CHANGELOG.md  CODE_OF_CONDUCT.md  CONTRIBUTING.md  LICENSE
├── pyproject.toml  requirements.txt  requirements-dev.txt
└── README.md  README.id.md
```

## Development

```bash
pip install -e ".[dev]"      # or: pip install -r requirements-dev.txt
pytest                       # run tests
ruff check .                 # lint
ruff format .                # format
```

## FAQ

**Why is the sessionid not a command-line flag, and why isn't it saved?**
Arguments end up in shell history and are visible to other processes, and a saved cookie is a
saved password. The value is kept in memory only, for the current run.

**Instagram answers with an HTTP error or "did not confirm".**
Your session may have expired, Instagram may have asked for a security check, or the internal
`client_doc_id` may have been rotated (pass a new one with `--doc-id`). Check the setting in the
official app, then see [Troubleshooting](docs/usage.md#troubleshooting).

**Can this get my account restricted?**
It uses an unofficial endpoint, so that risk cannot be ruled out. Use it sparingly and at your own risk.

**Does it send my session anywhere else?**
No. The value is sent only to `i.instagram.com`. Read `privacy.py`; the HTTP part is the
`InstagramClient` class.

## Roadmap

- [ ] Verify and document `unhide` behaviour on a real account
- [ ] Optional machine-readable output (`--json`)
- [ ] Publish to PyPI
- [ ] Screenshot / demo GIF

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) and the
[Code of Conduct](CODE_OF_CONDUCT.md). **Never paste a real `sessionid` into an issue or pull request.**

## License

[MIT](LICENSE) © 2024-2026 adilla

## Contact

- Issues: <https://github.com/seuv/instagram-follow-hide/issues>
- Telegram: <https://t.me/vjaci>