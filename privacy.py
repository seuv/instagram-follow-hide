#!/usr/bin/env python3
"""ig-follow-privacy: hide or unhide your Instagram followers/following list.

Single-file, standard-library-only tool (Python 3.9+).

    python privacy.py              # interactive menu
    python privacy.py hide         # one-shot: hide the lists
    python privacy.py unhide       # one-shot: show the lists again
    python privacy.py hide --dry-run

UNOFFICIAL. It calls an undocumented Instagram endpoint with your own ``sessionid``
cookie. That cookie gives full access to your account: never share or commit it.
Use only on an account you own. Not affiliated with Instagram or Meta.
"""

from __future__ import annotations

import argparse
import base64
import contextlib
import getpass
import http.client
import json
import logging
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Protocol

__version__ = "0.1.0"

logger = logging.getLogger("privacy")

# --------------------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------------------

ENV_SESSION_ID = "IG_SESSIONID"
ENV_DOC_ID = "IG_CLIENT_DOC_ID"
ENV_APP_ID = "IG_APP_ID"
ENV_USER_AGENT = "IG_USER_AGENT"
ENV_TIMEOUT = "IG_TIMEOUT"

# Fixed on purpose: the session cookie must only ever be sent to this URL.
ENDPOINT = "https://i.instagram.com/graphql/query"
SETTING_ID = "hide_followers_following_list"
MUTATION_NAME = "IGSettingsBooleanMutation"
RESPONSE_ROOT_KEY = "xdt_api__v1__settings__set_bool"

DEFAULT_APP_ID = "124024574287414"
DEFAULT_DOC_ID = "2669261950526978627082629536"
DEFAULT_USER_AGENT = "Instagram 453.0.0"
DEFAULT_TIMEOUT = 15.0

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_ERROR_BYTES = 16 * 1024

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130

_ERROR_FLAG_KEYS = ("error_name_value", "errorNameValue", "fallback_message", "fallbackMessage")
_SAFE_ERROR_KEYS = ("message", "error_type", "status", "code")

# --------------------------------------------------------------------------------------
# Exceptions
# --------------------------------------------------------------------------------------


class IGPrivacyError(Exception):
    """Base class for all expected errors raised by this tool (messages never hold secrets)."""


class ConfigurationError(IGPrivacyError):
    """A configuration value (CLI flag or environment variable) is invalid."""


class InvalidSessionIdError(IGPrivacyError):
    """The supplied ``sessionid`` value does not look like a valid cookie value."""


class RequestError(IGPrivacyError):
    """The HTTP request failed (network, TLS, HTTP status, redirect, bad body)."""


class SettingNotConfirmedError(IGPrivacyError):
    """Instagram answered, but did not confirm that the setting was changed."""


# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ClientConfig:
    """Tunable request parameters (none of them are secrets)."""

    app_id: str = DEFAULT_APP_ID
    doc_id: str = DEFAULT_DOC_ID
    user_agent: str = DEFAULT_USER_AGENT
    timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not self.app_id.isdigit():
            raise ConfigurationError("app id must contain digits only.")
        if not self.doc_id.isdigit():
            raise ConfigurationError("doc id must contain digits only.")
        if not self.user_agent or any(ord(c) < 32 or ord(c) > 126 for c in self.user_agent):
            raise ConfigurationError("user agent must be non-empty printable ASCII.")
        if not 0 < self.timeout <= 300:
            raise ConfigurationError("timeout must be between 0 and 300 seconds.")

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> ClientConfig:
        """Build a config from defaults overridden by ``IG_*`` environment variables."""
        env = os.environ if environ is None else environ
        base = cls()
        timeout_raw = env.get(ENV_TIMEOUT)
        try:
            timeout = float(timeout_raw) if timeout_raw else base.timeout
        except ValueError:
            raise ConfigurationError(f"{ENV_TIMEOUT} must be a number.") from None
        return cls(
            app_id=env.get(ENV_APP_ID) or base.app_id,
            doc_id=env.get(ENV_DOC_ID) or base.doc_id,
            user_agent=env.get(ENV_USER_AGENT) or base.user_agent,
            timeout=timeout,
        )

    def with_overrides(
        self,
        *,
        app_id: str | None = None,
        doc_id: str | None = None,
        user_agent: str | None = None,
        timeout: float | None = None,
    ) -> ClientConfig:
        """Return a copy with every non-``None`` argument replaced (and re-validated)."""
        changes = {
            "app_id": app_id,
            "doc_id": doc_id,
            "user_agent": user_agent,
            "timeout": timeout,
        }
        return replace(self, **{k: v for k, v in changes.items() if v is not None})


# --------------------------------------------------------------------------------------
# Authentication
# --------------------------------------------------------------------------------------

# A sessionid starts with the numeric user ID, then ":" (or its URL-encoded form "%3A").
_SESSION_PATTERN = re.compile(r"([1-9][0-9]*)(?::|%3[aA]).+")
_FORBIDDEN_CHARS = frozenset(';,"\\')


@dataclass(frozen=True)
class Credentials:
    """A validated session ID and the numeric user ID embedded in it."""

    user_id: str
    session_id: str = field(repr=False)

    def __repr__(self) -> str:  # never leak the secret through logs or tracebacks
        return f"Credentials(user_id={self.user_id!r}, session_id=<hidden>)"

    @classmethod
    def from_session_id(cls, raw: str) -> Credentials:
        """Validate ``raw`` and build credentials.

        Raises:
            InvalidSessionIdError: empty value, forbidden characters or unexpected format.
        """
        session_id = raw.strip()
        if session_id.lower().startswith("sessionid="):
            raise InvalidSessionIdError(
                "Enter only the sessionid cookie value, without 'sessionid='."
            )
        if not session_id or any(
            ord(c) <= 32 or ord(c) >= 127 or c in _FORBIDDEN_CHARS for c in session_id
        ):
            raise InvalidSessionIdError(
                "Enter only the sessionid cookie value, without 'sessionid=' "
                "and without spaces, quotes, commas or semicolons."
            )
        match = _SESSION_PATTERN.fullmatch(session_id)
        if not match:
            raise InvalidSessionIdError(
                "Invalid sessionid format: expected a numeric user ID followed by ':' or '%3A'."
            )
        return cls(user_id=match.group(1), session_id=session_id)

    @property
    def token(self) -> str:
        """Base64-encoded JSON payload used inside the Authorization header."""
        payload = json.dumps(
            {
                "ds_user_id": self.user_id,
                "sessionid": self.session_id,
                "should_use_header_over_cookies": True,
            },
            separators=(",", ":"),
        )
        return base64.b64encode(payload.encode()).decode("ascii")

    @property
    def authorization(self) -> str:
        """Value of the ``Authorization`` header."""
        return f"Bearer IGT:2:{self.token}"

    @property
    def cookie(self) -> str:
        """Value of the ``Cookie`` header."""
        return f"sessionid={self.session_id}; ds_user_id={self.user_id}"

    def secrets(self) -> set[str]:
        """Every string that must be scrubbed from error output."""
        return {
            self.authorization,
            self.token,
            self.session_id,
            urllib.parse.unquote(self.session_id),
            urllib.parse.quote(self.session_id, safe=""),
        }


# --------------------------------------------------------------------------------------
# HTTP client
# --------------------------------------------------------------------------------------


class _Opener(Protocol):
    """The slice of ``OpenerDirector`` used here (handy for test doubles)."""

    def open(self, fullurl: urllib.request.Request, timeout: float) -> Any: ...


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Refuse every redirect so credentials are never forwarded to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[override]
        raise RequestError("Redirect refused; credentials were not forwarded.")


def build_opener() -> urllib.request.OpenerDirector:
    """Create an opener with proxies disabled and redirects refused."""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())


@dataclass(frozen=True)
class SettingResult:
    """Outcome of a confirmed change."""

    user_id: str
    hidden: bool


def redact(text: str, secrets: set[str]) -> str:
    """Replace every secret (longest first) in ``text`` with ``<REDACTED>``."""
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, "<REDACTED>")
    return text


class InstagramClient:
    """Sends the settings mutation for a single account.

    Args:
        credentials: Validated session credentials.
        config: Request parameters; defaults are used when omitted.
        opener: Optional replacement for the URL opener (used in tests).
    """

    def __init__(
        self,
        credentials: Credentials,
        config: ClientConfig | None = None,
        opener: _Opener | None = None,
    ) -> None:
        self._credentials = credentials
        self._config = config or ClientConfig()
        self._opener: _Opener = opener or build_opener()

    def build_request(self, hidden: bool) -> urllib.request.Request:
        """Build (but do not send) the POST request for the requested state."""
        creds, cfg = self._credentials, self._config
        form = {
            "method": "post",
            "format": "json",
            "server_timestamps": "true",
            "locale": "user",
            "fb_api_req_friendly_name": MUTATION_NAME,
            "client_doc_id": cfg.doc_id,
            "variables": json.dumps(
                {
                    "setting_id": SETTING_ID,
                    "allow_error_codes": True,
                    "callsite": "account_privacy",
                    "value": hidden,
                }
            ),
        }
        headers = {
            "Authorization": creds.authorization,
            "Cookie": creds.cookie,
            "IG-INTENDED-USER-ID": creds.user_id,
            "X-IG-App-ID": cfg.app_id,
            "X-Auth-Type": "instagram",
            "User-Agent": cfg.user_agent,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept-Encoding": "identity",
            "X-GraphQL-Client-Library": "pando",
            "X-FB-Friendly-Name": MUTATION_NAME,
        }
        return urllib.request.Request(
            ENDPOINT,
            data=urllib.parse.urlencode(form).encode(),
            headers=headers,
            method="POST",
        )

    def set_lists_hidden(self, hidden: bool) -> SettingResult:
        """Hide (``True``) or unhide (``False``) the followers/following lists.

        The request is sent exactly once; nothing is retried automatically.

        Raises:
            RequestError: network/TLS failure, HTTP error, redirect or malformed body.
            SettingNotConfirmedError: Instagram did not echo the requested value.
        """
        request = self.build_request(hidden)
        logger.debug("Sending %s for user %s", MUTATION_NAME, self._credentials.user_id)
        body = self._send(request)
        self._confirm(body, hidden)
        return SettingResult(user_id=self._credentials.user_id, hidden=hidden)

    def _send(self, request: urllib.request.Request) -> dict[str, Any]:
        try:
            with self._opener.open(request, timeout=self._config.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise self._http_error(error) from None
        except (urllib.error.URLError, TimeoutError, OSError, http.client.HTTPException):
            raise RequestError("Network/TLS failure. No retry performed.") from None
        if len(raw) > MAX_RESPONSE_BYTES:
            raise RequestError("Response too large.")
        try:
            body = json.loads(raw)
        except ValueError:
            raise RequestError("Invalid JSON response. No retry performed.") from None
        if not isinstance(body, dict):
            raise RequestError("Unexpected JSON response shape. No retry performed.")
        return body

    def _http_error(self, error: urllib.error.HTTPError) -> RequestError:
        code = error.code
        with error:
            raw = error.read(MAX_ERROR_BYTES + 1)
        details: dict[str, Any] = {}
        try:
            body = json.loads(raw) if len(raw) <= MAX_ERROR_BYTES else {}
            if isinstance(body, dict):
                for key in _SAFE_ERROR_KEYS:
                    if isinstance(body.get(key), (str, int, bool)):
                        details[key] = body[key]
        except (ValueError, UnicodeError):
            pass
        text = json.dumps(details) if details else "No selected JSON error details."
        text = redact(text, self._credentials.secrets())
        return RequestError(f"HTTP {code}: {text[:1500]}. No retry performed.")

    @staticmethod
    def _extract_result(body: dict[str, Any]) -> dict[str, Any]:
        data = body.get("data")
        if not isinstance(data, dict):
            return {}
        matches = [
            value
            for key, value in data.items()
            if key == RESPONSE_ROOT_KEY or key.startswith(RESPONSE_ROOT_KEY + "(")
        ]
        if len(matches) == 1 and isinstance(matches[0], dict):
            return matches[0]
        return {}

    def _confirm(self, body: dict[str, Any], hidden: bool) -> None:
        result = self._extract_result(body)
        failed = (
            body.get("errors")
            or body.get("error")
            or body.get("status") == "fail"
            or result.get("value") is not hidden
            or any(result.get(key) for key in _ERROR_FLAG_KEYS)
        )
        if failed:
            action = "hiding" if hidden else "unhiding"
            raise SettingNotConfirmedError(
                f"Instagram did not confirm {action} the lists. No retry performed."
            )


# --------------------------------------------------------------------------------------
# Console UI
# --------------------------------------------------------------------------------------

_ART = r"""
 ___ ____   _____ ___  _     _     _____        __
|_ _/ ___| |  ___/ _ \| |   | |   / _ \ \      / /
 | | |  _  | |_ | | | | |   | |  | | | \ \ /\ / /
 | | |_| | |  _|| |_| | |___| |__| |_| |\ V  V /
|___\____| |_|   \___/|_____|_____\___/  \_/\_/
"""


def _use_utf8_streams() -> None:
    """Make box/check glyphs printable even when stdout is piped or a legacy codepage."""
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", "") or "").lower().replace("-", "")
        if encoding == "utf8":
            continue
        with contextlib.suppress(AttributeError, OSError, ValueError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]


def _enable_windows_ansi() -> None:
    """Turn on virtual-terminal processing so ANSI colors render on Windows."""
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
        mode = ctypes.c_uint32()
        if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


class Console:
    """Colored, timestamped console output (colors only on a real terminal).

    Results go to stdout; warnings and errors go to stderr. Set ``NO_COLOR`` to disable colors.
    """

    RED = "\x1b[91m"
    ORANGE = "\x1b[38;5;208m"
    GREEN = "\x1b[92m"
    YELLOW = "\x1b[93m"
    WHITE = "\x1b[97m"
    GREY = "\x1b[90m"
    RESET = "\x1b[0m"
    RULE = "─" * 44

    def __init__(self, color: bool | None = None) -> None:
        _use_utf8_streams()
        if color is None:
            color = sys.stdout.isatty() and "NO_COLOR" not in os.environ
        self.color = color
        if self.color and sys.platform == "win32":
            _enable_windows_ansi()

    def paint(self, text: str, code: str) -> str:
        """Wrap ``text`` in an ANSI color when colors are enabled."""
        return f"{code}{text}{self.RESET}" if self.color else text

    def _write(self, text: str = "", *, error: bool = False) -> None:
        print(text, file=sys.stderr if error else sys.stdout, flush=True)

    def _stamp(self) -> str:
        return self.paint(time.strftime("%H:%M:%S"), self.GREY)

    def _line(
        self,
        glyph: str,
        glyph_color: str,
        target: str,
        detail: str,
        detail_color: str,
        *,
        error: bool = False,
    ) -> None:
        dot = self.paint("·", self.GREY)
        self._write(
            f"  {self._stamp()} {self.paint(glyph, glyph_color)} "
            f"{self.paint(target, self.WHITE)} {dot} {self.paint(detail, detail_color)}",
            error=error,
        )

    def ok(self, target: str, detail: str) -> None:
        self._line("✓", self.GREEN, target, detail, self.GREEN)

    def warn(self, target: str, detail: str) -> None:
        self._line("!", self.YELLOW, target, detail, self.YELLOW, error=True)

    def err(self, target: str, detail: str) -> None:
        self._line("✗", self.RED, target, detail, self.RED, error=True)

    def info(self, detail: str) -> None:
        dot = self.paint("·", self.GREY)
        self._write(f"  {self._stamp()} {dot} {self.paint(detail, self.WHITE)}")

    def rule(self) -> None:
        self._write(f"  {self.paint(self.RULE, self.GREY)}")

    def blank(self) -> None:
        self._write()

    def clear(self) -> None:
        """Clear screen and scrollback (terminals only)."""
        if self.color:
            print("\x1b[2J\x1b[3J\x1b[H", end="", flush=True)

    def banner(self, *, clear: bool = False) -> None:
        """Print the ASCII banner; optionally clear the screen first."""
        if clear:
            self.clear()
        self.blank()
        for line in _ART.strip("\n").splitlines():
            self._write("  " + self.paint(line, self.ORANGE))
        self._write(
            f"  {self.paint('ig-follow-privacy', self.ORANGE)} {self.paint('·', self.GREY)} "
            f"{self.paint('hide / unhide followers list', self.WHITE)} "
            f"{self.paint('v' + __version__, self.GREY)}"
        )
        self._write(f"    {self.paint('unofficial · use only on your own account', self.GREY)}")
        self.blank()

    def ask(self, label: str = "") -> str:
        """Prompt for a line of input; returns ``""`` when stdin is closed."""
        try:
            return input(f"  {self.paint('›', self.ORANGE)} {label}")
        except EOFError:
            print()
            return ""

    def secret(self, label: str) -> str:
        """Prompt for hidden input; returns ``""`` when stdin is closed."""
        try:
            return getpass.getpass(f"  {self.paint(label, self.GREY)} ")
        except EOFError:
            return ""

    def pause(self) -> None:
        """Wait for Enter."""
        self.ask("press enter to continue ")


# --------------------------------------------------------------------------------------
# Actions shared by the menu and the one-shot commands
# --------------------------------------------------------------------------------------


def show_plan(
    console: Console, credentials: Credentials, config: ClientConfig, hidden: bool | None
) -> None:
    """Print what a request would contain, without any network call."""
    console.ok("session", f"valid · user id {credentials.user_id}")
    console.info(f"endpoint {ENDPOINT}")
    console.info(f"doc id {config.doc_id}")
    if hidden is None:
        console.info("hide sends value=true · unhide sends value=false")
    else:
        console.info(f"would set {SETTING_ID}={str(hidden).lower()}")
    console.ok("dry run", "no request was sent")


def perform(
    console: Console,
    credentials: Credentials,
    config: ClientConfig,
    hidden: bool,
    *,
    dry_run: bool = False,
) -> bool:
    """Hide/unhide (or just preview with ``dry_run``) and report. Returns ``True`` on success."""
    if dry_run:
        show_plan(console, credentials, config, hidden)
        return True
    action = "hide" if hidden else "unhide"
    console.info(f"sending {action} request...")
    try:
        result = InstagramClient(credentials, config).set_lists_hidden(hidden)
    except IGPrivacyError as error:
        console.err(action, str(error))
        return False
    if result.hidden:
        console.ok("hidden", "lists are now hidden · instagram returned value=true")
    else:
        console.ok("visible", "lists are now visible · instagram returned value=false")
    return True


class App:
    """Interactive numbered menu. The session lives in memory only and is never saved."""

    def __init__(
        self,
        console: Console,
        config: ClientConfig,
        credentials: Credentials | None = None,
    ) -> None:
        self.console = console
        self.config = config
        self.credentials = credentials
        self.last_action = "none yet"

    def run(self) -> int:
        """Run the menu loop and return an exit code."""
        c = self.console
        c.banner(clear=True)
        if self.credentials is None and not self._login(allow_env=True):
            return EXIT_ERROR
        while True:
            self._draw()
            choice = c.ask().strip().lower()
            c.blank()
            if choice == "1":
                self._act(True)
            elif choice == "2":
                self._act(False)
            elif choice == "3":
                self._preview()
            elif choice == "4":
                self._login(allow_env=False)
            elif choice in ("5", "q", "quit", "exit", ""):
                return EXIT_OK
            else:
                c.warn("input", "invalid option")
                time.sleep(0.8)

    def _draw(self) -> None:
        c = self.console
        assert self.credentials is not None
        c.clear()
        c.banner()
        c.info(f"session {c.paint('user id ' + self.credentials.user_id, c.ORANGE)}")
        c.info(f"last action {c.paint(self.last_action, c.ORANGE)}")
        c.rule()
        for number, text in (
            ("1", "hide followers/following list"),
            ("2", "unhide followers/following list"),
            ("3", "preview request (dry run)"),
            ("4", "change session"),
            ("5", "exit"),
        ):
            c.info(f"{c.paint(number, c.ORANGE)} · {text}")
        c.rule()

    def _act(self, hidden: bool) -> None:
        c = self.console
        assert self.credentials is not None
        c.rule()
        success = perform(c, self.credentials, self.config, hidden)
        name = "hide" if hidden else "unhide"
        self.last_action = f"{name} · {'ok' if success else 'failed'} · {time.strftime('%H:%M:%S')}"
        c.rule()
        c.pause()

    def _preview(self) -> None:
        assert self.credentials is not None
        self.console.rule()
        show_plan(self.console, self.credentials, self.config, None)
        self.console.rule()
        self.console.pause()

    def _login(self, *, allow_env: bool) -> bool:
        """Obtain and validate a session value (up to 3 attempts). Empty input cancels."""
        c = self.console
        from_env = os.environ.get(ENV_SESSION_ID) if allow_env else None
        c.info("paste your instagram sessionid value (typing is hidden, empty to cancel)")
        for _ in range(3):
            raw = from_env or c.secret("sessionid:")
            from_env = None
            if not raw.strip():
                c.info("cancelled" if self.credentials is None else "session unchanged")
                return False
            try:
                self.credentials = Credentials.from_session_id(raw)
            except InvalidSessionIdError as error:
                c.err("session", str(error))
                continue
            c.ok("session", f"loaded · user id {self.credentials.user_id}")
            time.sleep(0.5)
            return True
        c.err("session", "too many invalid attempts")
        return False


# --------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser (exposed for tests and documentation)."""
    network = argparse.ArgumentParser(add_help=False)
    network.add_argument("--doc-id", help="override the client_doc_id (env: IG_CLIENT_DOC_ID)")
    network.add_argument("--app-id", help="override the X-IG-App-ID header (env: IG_APP_ID)")
    network.add_argument("--user-agent", help="override the User-Agent header (env: IG_USER_AGENT)")
    network.add_argument(
        "--timeout", type=float, help="request timeout in seconds (env: IG_TIMEOUT, default 15)"
    )
    network.add_argument("-v", "--verbose", action="store_true", help="show debug logging")

    oneshot = argparse.ArgumentParser(add_help=False)
    oneshot.add_argument(
        "--stdin", action="store_true", help="read the sessionid value from the first line of stdin"
    )
    oneshot.add_argument(
        "--dry-run",
        action="store_true",
        help="validate the session and print the plan, without any network call",
    )
    oneshot.add_argument("--no-banner", action="store_true", help="do not print the ASCII banner")

    parser = argparse.ArgumentParser(
        prog="ig-follow-privacy",
        description="Hide or unhide your Instagram followers/following list. "
        "Run without a command for the interactive menu.",
        epilog=(
            f"The sessionid value is read from --stdin if given, else from ${ENV_SESSION_ID}, "
            "else from a hidden prompt. It is never accepted as a command-line argument."
        ),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="{menu,hide,unhide}")
    sub.add_parser("menu", parents=[network], help="interactive menu (default without a command)")
    sub.add_parser("hide", parents=[network, oneshot], help="hide the followers/following list")
    sub.add_parser("unhide", parents=[network, oneshot], help="make the list visible again")
    return parser


def _configure_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(levelname)s: %(message)s",
        stream=sys.stderr,
    )


def _read_session_id(use_stdin: bool, console: Console) -> str:
    """Obtain the session value without ever accepting it as a CLI argument."""
    if use_stdin:
        return sys.stdin.readline()
    from_env = os.environ.get(ENV_SESSION_ID)
    if from_env:
        logger.debug("Using session value from %s", ENV_SESSION_ID)
        return from_env
    return console.secret("sessionid (hidden):")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return a process exit code."""
    raw_args = list(sys.argv[1:] if argv is None else argv)
    args = build_parser().parse_args(raw_args or ["menu"])
    _configure_logging(args.verbose)
    console = Console()

    try:
        config = ClientConfig.from_env().with_overrides(
            app_id=args.app_id,
            doc_id=args.doc_id,
            user_agent=args.user_agent,
            timeout=args.timeout,
        )
    except IGPrivacyError as error:
        console.err("config", str(error))
        return EXIT_ERROR

    if args.command == "menu":
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            console.err("menu", "the interactive menu needs a terminal · use: hide | unhide")
            return EXIT_USAGE
        return App(console, config).run()

    if not args.no_banner and sys.stdout.isatty():
        console.banner()
    try:
        credentials = Credentials.from_session_id(_read_session_id(args.stdin, console))
    except InvalidSessionIdError as error:
        console.err("session", str(error))
        return EXIT_ERROR
    ok = perform(console, credentials, config, args.command == "hide", dry_run=args.dry_run)
    return EXIT_OK if ok else EXIT_ERROR


def run() -> None:
    """Console entry point: converts ``Ctrl+C`` into a friendly message."""
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print()
        Console().warn(
            "exit", "interrupted · the update may have been applied; check before retrying"
        )
        raise SystemExit(EXIT_INTERRUPTED) from None


if __name__ == "__main__":
    run()
