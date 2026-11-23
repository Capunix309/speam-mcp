"""Manage Jira, XWiki, and Google Sheets credentials in the native credential store."""

from __future__ import annotations

import argparse
import getpass

from .shared import credential_store


INTEGRATIONS = ("jira", "xwiki", "sheets")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Manage Jira, XWiki, and Google Sheets credentials in the native system credential manager."
    )
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("set", "status", "remove"):
        command = commands.add_parser(action)
        command.add_argument("integration", choices=INTEGRATIONS)
        if action == "set":
            command.add_argument(
                "client_json",
                nargs="?",
                help="Google OAuth Desktop client JSON path (Sheets only; optional after first import)",
            )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = _parser().parse_args(argv)
    integration = args.integration

    try:
        if args.action == "set":
            if integration == "sheets":
                from .integrations.automation.core.sheets.authorize import main as authorize_sheets

                authorize_sheets([args.client_json] if args.client_json else [])
                return
            if args.client_json:
                raise SystemExit("A client JSON path is only valid for Sheets.")
            username = input(f"{integration.upper()} username: ").strip()
            password = getpass.getpass(f"{integration.upper()} password: ")
            confirmation = getpass.getpass("Confirm password: ")
            if not username or not password:
                raise SystemExit("Username and password must both be non-empty.")
            if password != confirmation:
                raise SystemExit("Passwords do not match; nothing was saved.")
            credential_store.set_integration_credentials(integration, username, password)
            print(f"{integration.upper()} credentials saved to the native credential store.")
        elif args.action == "status":
            if integration == "sheets":
                present = credential_store.sheets_credentials_present()
            else:
                credentials = credential_store.get_integration_credentials(integration)
                present = credentials is not None and bool(credentials[0]) and bool(credentials[1])
            print(f"{integration.upper()} credentials: {'present' if present else 'missing'}.")
            print("No credential values were displayed.")
        else:
            if integration == "sheets":
                credential_store.delete_sheets_credentials()
            else:
                credential_store.delete_integration_credentials(integration)
            print(f"{integration.upper()} credentials removed from the native credential store.")
    except credential_store.CredentialStoreError as error:
        raise SystemExit(str(error)) from None


if __name__ == "__main__":
    main()
