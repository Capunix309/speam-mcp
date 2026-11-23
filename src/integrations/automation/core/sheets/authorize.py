"""Import a Google OAuth client into the native credential store and authorize Sheets."""

from __future__ import annotations

import argparse
import json
import platform
import re
from pathlib import Path
from typing import Any

from .auth import (
    KEYCHAIN_ACCOUNT,
    KEYCHAIN_CLIENT_ACCOUNT,
    KEYCHAIN_SERVICE,
    SCOPES,
    _keychain,
)


def _keychain_error(stage: str, error: Exception) -> str:
    """Describe a native credential-store failure without exposing backend payloads."""
    from src.shared.credential_store import CredentialStoreError

    if isinstance(error, CredentialStoreError):
        return f"Could not {stage}: {error}"
    message = str(error)
    match = re.search(r"\((-?\d+),", message)
    code = int(match.group(1)) if match else None
    known = {
        -50: ("errSecParam", "The macOS Security framework rejected a parameter in the Keychain request."),
        -128: ("errSecUserCanceled", "macOS denied or canceled the Keychain operation."),
        -25293: ("errSecAuthFailed", "macOS could not authorize access to the Keychain."),
        -25300: ("errSecItemNotFound", "The requested Keychain entry does not exist."),
        -25308: ("errSecInteractionNotAllowed", "macOS did not allow the Keychain interaction in this process."),
    }
    if platform.system() == "Darwin" and code in known:
        code_name, explanation = known[code]
        return f"Could not {stage}: {explanation} ({code_name}, OSStatus {code})."
    if code is not None and platform.system() == "Darwin":
        return f"Could not {stage}: the macOS Keychain returned OSStatus {code}."
    return f"Could not {stage}: {type(error).__name__}. No credential value was displayed."


def _exception_chain(error: Exception):
    """Yield wrapped exceptions so transport errors can be classified safely."""
    current = error
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = current.__cause__ or current.__context__


def _oauth_transport_error(error: Exception) -> str | None:
    """Return a safe, specific diagnosis for TLS errors without echoing details."""
    chain = list(_exception_chain(error))
    if not any(type(item).__name__ in {"SSLError", "CertificateError"} for item in chain):
        return None

    messages = " ".join(str(item).lower() for item in chain)
    certificate_errors = (
        "certificate verify failed",
        "certificate_verify_failed",
        "unable to get local issuer certificate",
        "self-signed certificate",
        "hostname mismatch",
    )
    if any(reason in messages for reason in certificate_errors):
        return (
            "Google OAuth could not verify the HTTPS certificate. Check the system/Python CA trust, "
            "the system date and time, and whether a VPN or proxy is intercepting TLS. This is a "
            "connection trust problem, not evidence that the consent screen or Google credentials are wrong."
        )
    if "wrong_version_number" in messages or "wrong version number" in messages:
        return (
            "Google OAuth TLS negotiation failed because the peer did not speak the expected TLS protocol. "
            "Check proxy URL and VPN/proxy settings; this can happen when HTTPS traffic is sent to a "
            "plain HTTP proxy endpoint."
        )
    if "unexpected_eof" in messages or "eof occurred in violation of protocol" in messages:
        return (
            "The connection closed during Google OAuth TLS negotiation. Check for a network filter, "
            "VPN/proxy interruption, or TLS inspection."
        )
    return (
        "Google OAuth could not complete its TLS connection. Check network access, VPN/proxy TLS "
        "inspection, and certificate trust. This is a connection problem, not evidence that the "
        "consent screen or Google credentials are wrong."
    )


def _check_keychain(keyring) -> None:
    """Verify credential-store reads and report only whether expected entries exist."""
    try:
        client_config = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_CLIENT_ACCOUNT)
    except Exception as error:
        raise SystemExit(_keychain_error("read the saved OAuth client configuration", error)) from None
    try:
        token = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT)
    except Exception as error:
        raise SystemExit(_keychain_error("read the saved Sheets authorization", error)) from None

    print("Native credential-store read access: OK")
    print(f"OAuth client configuration: {'present' if client_config else 'missing'}")
    print(f"Sheets authorization token: {'present' if token else 'missing'}")
    print("No credential values were displayed or changed.")


def _check_google_tls() -> None:
    """Probe Google's OAuth endpoint without sending credentials or starting OAuth."""
    try:
        import requests
    except ImportError:
        raise SystemExit("Install MCP-tools dependencies first with: pip install -r requirements.txt") from None

    try:
        response = requests.head(
            "https://oauth2.googleapis.com/token",
            timeout=10,
            allow_redirects=False,
        )
    except Exception as error:
        transport_error = _oauth_transport_error(error)
        if transport_error:
            raise SystemExit(transport_error) from None
        if isinstance(error, requests.Timeout):
            raise SystemExit(
                "The credential-free connection to Google's OAuth endpoint timed out. "
                "Check network access, VPN, and proxy settings."
            ) from None
        if isinstance(error, requests.ConnectionError):
            raise SystemExit(
                "Could not connect to Google's OAuth endpoint. Check DNS, network access, VPN, and proxy settings."
            ) from None
        raise SystemExit(
            f"The credential-free OAuth endpoint probe failed ({type(error).__name__})."
        ) from None

    print(f"Google OAuth endpoint TLS: OK (HTTP {response.status_code}; no credentials sent).")


def _read_client_config(path: Path) -> dict[str, Any]:
    """Read and validate the installed-app JSON downloaded from Google Cloud."""
    try:
        client_config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise ValueError("Could not read a valid OAuth client JSON file from the supplied path.") from None
    if not isinstance(client_config, dict) or not isinstance(client_config.get("installed"), dict):
        raise ValueError("The supplied JSON must be a Google OAuth Desktop app client.")
    installed = client_config["installed"]
    if not installed.get("client_id") or not installed.get("auth_uri") or not installed.get("token_uri"):
        raise ValueError("The OAuth Desktop app JSON is missing required client settings.")
    return client_config


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Import a Google OAuth Desktop client into the native credential store and authorize Sheets access."
    )
    parser.add_argument(
        "client_json",
        nargs="?",
        type=Path,
        help="path to the downloaded OAuth Desktop app JSON; optional after the first import",
    )
    parser.add_argument(
        "--check-credential-store", "--check-keychain",
        dest="check_keychain",
        action="store_true",
        help="read-check the native credential store and report only whether MCP entries exist",
    )
    parser.add_argument(
        "--check-google-tls",
        action="store_true",
        help="check HTTPS to Google's OAuth endpoint without authenticating",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    """Authorize from a supplied client JSON or the copy already in the credential store."""
    args = _parser().parse_args(argv)
    if (args.check_keychain or args.check_google_tls) and args.client_json:
        raise SystemExit("Do not pass a client JSON path with a diagnostic option.")

    if args.check_google_tls:
        _check_google_tls()
    if args.check_keychain:
        try:
            keyring = _keychain()
        except Exception as error:
            raise SystemExit(_keychain_error("initialize the native credential-store backend", error)) from None
        _check_keychain(keyring)
    if args.check_keychain or args.check_google_tls:
        return

    try:
        keyring = _keychain()
    except Exception as error:
        raise SystemExit(_keychain_error("initialize the native credential-store backend", error)) from None

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
    except ImportError:
        raise SystemExit("Install MCP-tools dependencies first with: pip install -r requirements.txt") from None

    source_path = args.client_json.expanduser().resolve() if args.client_json else None
    if source_path:
        try:
            client_config = _read_client_config(source_path)
        except ValueError as exc:
            raise SystemExit(str(exc)) from None
        try:
            keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_CLIENT_ACCOUNT, json.dumps(client_config))
        except Exception as error:
            raise SystemExit(_keychain_error("store the OAuth client configuration", error)) from None
    else:
        try:
            saved_config = keyring.get_password(KEYCHAIN_SERVICE, KEYCHAIN_CLIENT_ACCOUNT)
        except Exception as error:
            raise SystemExit(_keychain_error("read the saved OAuth client configuration", error)) from None
        if not saved_config:
            raise SystemExit(
                "Pass the downloaded OAuth Desktop app JSON path the first time; "
                "after importing it, the argument is optional. Use `python -m src.credentials set sheets [client.json]`."
            )
        try:
            client_config = json.loads(saved_config)
        except json.JSONDecodeError:
            raise SystemExit("The OAuth client entry in the credential store is invalid; import the JSON file again.") from None

    try:
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    except Exception as error:
        raise SystemExit(
            f"Could not prepare Google OAuth from the Desktop client configuration ({type(error).__name__}). "
            "Check that the file is a valid OAuth Desktop app client."
        ) from None
    try:
        credentials = flow.run_local_server(port=0, open_browser=True)
    except Exception as error:
        transport_error = _oauth_transport_error(error)
        if transport_error:
            raise SystemExit(transport_error) from None
        raise SystemExit(
            f"Google sign-in or token exchange failed ({type(error).__name__}). "
            "Check that the OAuth consent screen allows this account and that the Desktop OAuth client is active."
        ) from None
    try:
        token_json = credentials.to_json()
    except Exception as error:
        raise SystemExit(
            f"Google sign-in completed, but the returned credentials could not be serialized "
            f"({type(error).__name__}). No credential values were displayed."
        ) from None
    try:
        keyring.set_password(KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT, token_json)
    except Exception as error:
        raise SystemExit(
            _keychain_error("save the Google authorization token", error)
            + " Google sign-in may have succeeded, but the token was not stored."
        ) from None

    source_removed = False
    if source_path:
        try:
            source_path.unlink()
            source_removed = True
        except OSError:
            pass

    print("Google Sheets authorization complete. The client and refreshable token are stored in the native credential store.")
    if source_path and source_removed:
        print("The imported OAuth JSON file was removed from its original location.")
    elif source_path:
        print("Remove the downloaded OAuth JSON file manually; the credential store has the client configuration.")


if __name__ == "__main__":
    main()
