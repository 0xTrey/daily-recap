#!/usr/bin/env python3
"""
Google API Authentication Setup for Daily Recap.

Adapted from weekly-report/setup_google_auth.py.
Runs OAuth flow and saves token.json to this project root.

Prerequisites:
1. credentials.json symlinked from ~/weekly-report/credentials.json
2. Google Cloud project with Calendar, Gmail, Docs, Drive APIs enabled
"""

import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/drive.file",
]

PROJECT_ROOT = Path(__file__).parent


def check_dependencies():
    missing = []
    try:
        from google.oauth2.credentials import Credentials  # noqa: F401
    except ImportError:
        missing.append("google-auth")
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # noqa: F401
    except ImportError:
        missing.append("google-auth-oauthlib")
    try:
        from googleapiclient.discovery import build  # noqa: F401
    except ImportError:
        missing.append("google-api-python-client")

    if missing:
        print(f"Missing packages. Install with: pip install {' '.join(missing)}")
        sys.exit(1)


def setup_credentials():
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request

    credentials_path = PROJECT_ROOT / "credentials.json"
    token_path = PROJECT_ROOT / "token.json"

    if not credentials_path.exists():
        print("credentials.json not found.")
        print(f"Symlink it from weekly-report: ln -s ~/weekly-report/credentials.json {credentials_path}")
        sys.exit(1)

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired credentials...")
            creds.refresh(Request())
        else:
            print("Starting OAuth flow - a browser window will open.")
            flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
            creds = flow.run_local_server(port=0)

        with open(token_path, "w") as f:
            f.write(creds.to_json())
        print(f"Credentials saved to {token_path}")

    return creds


def verify_access(creds):
    from googleapiclient.discovery import build

    print("Verifying API access...")

    apis = [
        ("Calendar", lambda: build("calendar", "v3", credentials=creds).calendarList().list(maxResults=1).execute()),
        ("Gmail", lambda: build("gmail", "v1", credentials=creds).users().getProfile(userId="me").execute()),
        ("Docs", lambda: build("docs", "v1", credentials=creds)),
        ("Drive", lambda: build("drive", "v3", credentials=creds).files().list(pageSize=1).execute()),
    ]

    for name, test_fn in apis:
        try:
            test_fn()
            print(f"  {name} API: OK")
        except Exception as e:
            print(f"  {name} API: FAILED - {e}")


def main():
    print("Daily Recap - Google API Auth Setup")
    print("=" * 40)
    check_dependencies()
    creds = setup_credentials()
    verify_access(creds)
    print("\nSetup complete. You can now run: python daily_recap.py")


if __name__ == "__main__":
    main()
