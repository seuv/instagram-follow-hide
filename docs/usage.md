# Usage guide

## Features

| Command | What it does |
| --- | --- |
| `hide` | Sends `hide_followers_following_list = true` for the account that owns the session. |
| `unhide` | Sends `hide_followers_following_list = false`. |

Both commands ask Instagram to change one setting, then check that Instagram echoed the requested
value. If it did not, the command fails with exit code `1`.

## Interactive menu

Run `python3 privacy.py` (or `ig-follow-privacy`) with no arguments in a terminal.

| Key | Action |
| --- | --- |
| `1` | Hide the followers/following list |
| `2` | Unhide it |
| `3` | Preview the request (dry run, nothing is sent) |
| `4` | Change the session (hidden prompt) |
| `5` / `q` / Enter | Exit |

The session is asked once at start (or taken from `IG_SESSIONID`) and kept **in memory only**.
The menu shows the result of your last action in this run; it does not read the current
setting from Instagram. Network options (`--doc-id`, `--app-id`, `--user-agent`, `--timeout`, `-v`)
also work with the menu: `python3 privacy.py menu --timeout 30`. Without a terminal
(for example in a pipe) the menu refuses to start and exits with code `2`.

## Providing the session value

The `sessionid` cookie value is read from the first source that applies:

1. `--stdin` – first line of standard input.
2. `IG_SESSIONID` – environment variable.
3. A hidden interactive prompt (`getpass`).

It is deliberately **not** a command-line argument. Enter the value only, e.g.
`12345678%3AAbCd...`, not `sessionid=12345678...`. Leading/trailing whitespace is trimmed; spaces,
quotes, commas, semicolons and non-ASCII characters are rejected.

## Command-line arguments

Both `hide` and `unhide` accept:

| Argument | Description | Default |
| --- | --- | --- |
| `--stdin` | Read the session value from stdin. | off |
| `--dry-run` | Validate and print the plan; no network call. | off |
| `--doc-id DIGITS` | Override `client_doc_id` (env `IG_CLIENT_DOC_ID`). | built-in |
| `--app-id DIGITS` | Override `X-IG-App-ID` (env `IG_APP_ID`). | built-in |
| `--user-agent TEXT` | Override `User-Agent` (env `IG_USER_AGENT`). | `Instagram 453.0.0` |
| `--timeout SECONDS` | Request timeout, 0 < value ≤ 300 (env `IG_TIMEOUT`). | `15` |
| `--no-banner` | Do not print the ASCII banner. | banner shown on a terminal |
| `-v`, `--verbose` | Debug logging on stderr (never contains the session value). | off |

Top level: `--version`, `-h/--help`.

The banner is printed only when stdout is a terminal, so pipes and scripts are not affected. Colors are
used only on a terminal and are disabled by `NO_COLOR`.

## Examples

```bash
python3 privacy.py hide
python3 privacy.py unhide --timeout 30
python3 privacy.py hide --dry-run
IG_SESSIONID='12345678%3A...' python3 privacy.py hide --no-banner
pass show instagram/session | python3 privacy.py hide --stdin     # from a password manager
```

Use as a library: [`examples/use_as_library.py`](../examples/use_as_library.py).

## Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Instagram confirmed the change (or `--dry-run` finished). |
| 1 | Invalid session/config, network or HTTP failure, or change not confirmed. |
| 2 | Invalid command-line usage (argparse). |
| 130 | Interrupted (Ctrl+C). The change may or may not have been applied. |

## Troubleshooting

| Symptom | Likely cause and fix |
| --- | --- |
| `Enter only the sessionid cookie value...` | You pasted `sessionid=...` or included quotes/semicolons. Paste only the value. |
| `Invalid sessionid format` | The value must start with digits followed by `:` or `%3A`. Copy the cookie again. |
| `HTTP 400/401/403 ...` | Session expired or logged out, a security check is pending, or the request was rejected. Log in again in the browser/app, resolve any prompt, copy a fresh `sessionid`. |
| `HTTP 4xx` right after it worked before | `client_doc_id` may have been rotated by Instagram. Try `--doc-id <new value>`. How to obtain a current value is outside the scope of this project. |
| `Instagram did not confirm ...` | The response did not contain the expected value. Check the setting in the official app before retrying. |
| `Redirect refused` | Instagram redirected the request. Credentials are never forwarded; do not work around this. |
| `Network/TLS failure` | No connection, DNS/firewall/VPN issue or timeout. Try `--timeout 30`. System proxies are intentionally ignored. |
| `Interrupted. The update may have been applied` | Check the setting in the app before running again. |

Add `-v` to see which step failed (debug output never includes secrets).

## Limitations

- Works on **one account at a time**, the one that owns the session.
- Controls a single setting: `hide_followers_following_list`.
- Relies on an **undocumented** endpoint and a `client_doc_id` that Instagram can change without notice.
- No automatic retries, proxies or redirects, by design.
- Automated tests use a mocked HTTP layer. `unhide` not yet been verified against a real account.
- No GUI, no account login, no 2FA handling: you provide an existing session.

## Upgrading

```bash
cd ig-follow-privacy
git pull
python3 privacy.py --version
# only if you installed it with pip:
pip install --upgrade .
```

See [CHANGELOG.md](../CHANGELOG.md) for what changed.
