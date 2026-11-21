"""Use ig-follow-privacy from Python code instead of the CLI.

Run with:
    export IG_SESSIONID='<your sessionid value>'
    python examples/use_as_library.py hide      # or: unhide
"""

from __future__ import annotations

import os
import sys

from privacy import Credentials, IGPrivacyError, InstagramClient


def main() -> int:
    action = sys.argv[1] if len(sys.argv) > 1 else "hide"
    if action not in {"hide", "unhide"}:
        print("usage: use_as_library.py [hide|unhide]", file=sys.stderr)
        return 2

    try:
        credentials = Credentials.from_session_id(os.environ["IG_SESSIONID"])
        result = InstagramClient(credentials).set_lists_hidden(action == "hide")
    except KeyError:
        print("Set the IG_SESSIONID environment variable first.", file=sys.stderr)
        return 1
    except IGPrivacyError as error:
        print(error, file=sys.stderr)
        return 1

    print(f"user {result.user_id}: lists hidden = {result.hidden}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
