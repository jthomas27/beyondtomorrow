"""Credential checks must support a renewed CLI session without leaking tokens."""
from types import SimpleNamespace
from scripts import auth_check


def test_cli_session_fallback_ignores_stale_personal_token(monkeypatch, mocker, capsys):
    monkeypatch.setenv("RAILWAY_API_TOKEN", "test-stale-token")
    run = mocker.patch("subprocess.run", side_effect=[
        SimpleNamespace(returncode=1, stdout="", stderr="Unauthorized"),
        SimpleNamespace(returncode=0, stdout="private account metadata", stderr=""),
    ])
    auth_check.check_railway()
    assert "RAILWAY_API_TOKEN" not in run.call_args_list[1].kwargs["env"]
    output = capsys.readouterr().out
    assert "confirmed" in output and "test-stale-token" not in output
    assert "private account metadata" not in output


def test_credential_display_has_no_secret_prefix():
    assert auth_check.mask("test-credential") == "[set]"
