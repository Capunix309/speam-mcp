"""Tests for native credential storage and portable user configuration."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.shared import credential_store
from src.shared import paths
from src.shared.paths import migrate_legacy_config


class CredentialStoreTests(unittest.TestCase):
    def test_only_native_platform_backends_are_accepted(self):
        self.assertTrue(credential_store._backend_is_native("Windows", "keyring.backends.Windows.WinVaultKeyring"))
        self.assertTrue(credential_store._backend_is_native("Darwin", "keyring.backends.macOS.Keyring"))
        self.assertTrue(credential_store._backend_is_native("Linux", "keyring.backends.SecretService.Keyring"))
        self.assertFalse(credential_store._backend_is_native("Windows", "keyrings.alt.file.PlaintextKeyring"))
        self.assertFalse(credential_store._backend_is_native("Linux", "keyring.backends.fail.Keyring"))

    def test_integration_credentials_are_stored_as_one_native_record(self):
        fake = Mock()
        fake.get_password.return_value = json.dumps({"username": "user", "password": "secret"})
        with patch.object(credential_store, "keyring_module", return_value=fake):
            self.assertEqual(
                credential_store.get_integration_credentials("jira"),
                ("user", "secret"),
            )
            credential_store.set_integration_credentials("xwiki", "wiki-user", "wiki-secret")
        args = fake.set_password.call_args.args
        self.assertEqual(args[:2], (credential_store.INTEGRATION_CREDENTIAL_SERVICE, "xwiki"))
        self.assertEqual(json.loads(args[2]), {"username": "wiki-user", "password": "wiki-secret"})

    def test_sheets_status_requires_oauth_client_and_token(self):
        fake = Mock()
        fake.get_password.side_effect = ["oauth-client", None, "oauth-client", "token"]
        credential_store.get_secret.cache_clear()
        with patch.object(credential_store, "keyring_module", return_value=fake):
            self.assertFalse(credential_store.sheets_credentials_present())
            credential_store.get_secret.cache_clear()
            self.assertTrue(credential_store.sheets_credentials_present())
        credential_store.get_secret.cache_clear()

    def test_config_migration_moves_only_when_destination_is_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "old" / "config.toml"
            destination = root / "user" / "config.toml"
            source.parent.mkdir()
            source.write_text("private config", encoding="utf-8")
            self.assertTrue(migrate_legacy_config(source, destination))
            self.assertFalse(source.exists())
            self.assertEqual(destination.read_text(encoding="utf-8"), "private config")
            source.write_text("second config", encoding="utf-8")
            self.assertFalse(migrate_legacy_config(source, destination))
            self.assertEqual(destination.read_text(encoding="utf-8"), "private config")

    def test_windows_config_uses_roaming_appdata_with_vendor_directory(self):
        with patch.object(paths.platform, "system", return_value="Windows"), patch.dict(
            "os.environ",
            {"APPDATA": "C:/Users/test/AppData/Roaming", "MCP_TOOLS_CONFIG_DIR": ""},
        ):
            self.assertEqual(
                paths.config_dir(),
                Path("C:/Users/test/AppData/Roaming/Capunix/mcp-tools"),
            )

    def test_credentials_cli_never_prints_password(self):
        from src import credentials

        output = io.StringIO()
        with (
            patch("builtins.input", return_value="jira-user"),
            patch("getpass.getpass", side_effect=["very-secret", "very-secret"]),
            patch.object(credential_store, "set_integration_credentials") as save,
            contextlib.redirect_stdout(output),
        ):
            credentials.main(["set", "jira"])
        save.assert_called_once_with("jira", "jira-user", "very-secret")
        self.assertNotIn("very-secret", output.getvalue())

    def test_credentials_cli_routes_sheets_set_through_oauth_flow(self):
        from src import credentials

        with patch(
            "src.integrations.automation.core.sheets.authorize.main"
        ) as authorize_sheets:
            credentials.main(["set", "sheets", "/tmp/oauth-client.json"])
        authorize_sheets.assert_called_once_with(["/tmp/oauth-client.json"])


if __name__ == "__main__":
    unittest.main()
