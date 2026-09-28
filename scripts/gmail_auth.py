"""Authorise read-only Gmail access. Run on the desktop: scripts/gmail_auth.bat"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.config import settings  # noqa: E402
from backend.gmail.client import GmailNotConfigured, run_oauth_flow  # noqa: E402

if __name__ == "__main__":
    settings.ensure_dirs()
    try:
        account = run_oauth_flow()
    except GmailNotConfigured as exc:
        sys.exit(str(exc))
    print(f"Gmail connected: {account}")
    print(f"Token saved to {settings.gmail_token_file} (keep this file private; it is not in Git).")
    print("The app will now check Gmail automatically. You can also press 'Sync Gmail Now'.")
