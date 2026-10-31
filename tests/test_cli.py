import getpass
import stat
import warnings

import pytest

from pipeline import __version__, cli, keystore, paths

KEY = "synthetic-key-value-1"


@pytest.fixture
def terminal(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)


def enter_key(monkeypatch, value=KEY):
    prompts = []

    def fake_getpass(prompt):
        prompts.append(prompt)
        return value

    monkeypatch.setattr(getpass, "getpass", fake_getpass)
    return prompts


def test_version(capsys):
    with pytest.raises(SystemExit) as code:
        cli.main(["--version"])
    assert code.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_set_key_stores_the_key_without_printing_it(terminal, monkeypatch, capsys):
    prompts = enter_key(monkeypatch)
    assert cli.main(["set-key", "eodhd"]) == 0
    captured = capsys.readouterr()
    assert KEY not in captured.out + captured.err
    assert KEY not in prompts[0]
    assert keystore.load_key("eodhd", paths.secrets_path()) == KEY
    assert stat.S_IMODE(paths.secrets_path().stat().st_mode) == 0o600


def test_set_key_refuses_without_a_terminal(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    prompts = enter_key(monkeypatch)
    assert cli.main(["set-key", "eodhd"]) == 1
    assert "terminal" in capsys.readouterr().err
    assert prompts == []
    assert not paths.secrets_path().exists()


def test_set_key_refuses_when_input_cannot_be_hidden(terminal, monkeypatch, capsys):
    def echoing_getpass(_prompt):
        warnings.warn("Can not control echo", getpass.GetPassWarning, stacklevel=2)
        return KEY

    monkeypatch.setattr(getpass, "getpass", echoing_getpass)
    assert cli.main(["set-key", "eodhd"]) == 1
    assert "ocultar" in capsys.readouterr().err
    assert not paths.secrets_path().exists()


def test_set_key_rejects_an_empty_key(terminal, monkeypatch, capsys):
    enter_key(monkeypatch, "   ")
    assert cli.main(["set-key", "eodhd"]) == 1
    assert "ninguna clave" in capsys.readouterr().err
    assert not paths.secrets_path().exists()


def test_set_key_invalid_key_is_not_echoed(terminal, monkeypatch, capsys):
    bad_key = 'synthetic"invalid-key'
    enter_key(monkeypatch, bad_key)
    assert cli.main(["set-key", "eodhd"]) == 1
    captured = capsys.readouterr()
    assert bad_key not in captured.out + captured.err


def test_set_key_asks_before_replacing(terminal, monkeypatch, capsys):
    keystore.save_key("eodhd", KEY, paths.secrets_path())
    prompts = enter_key(monkeypatch, "synthetic-key-value-2")
    monkeypatch.setattr("builtins.input", lambda _prompt: "n")
    assert cli.main(["set-key", "eodhd"]) == 0
    assert prompts == []
    assert keystore.load_key("eodhd", paths.secrets_path()) == KEY

    monkeypatch.setattr("builtins.input", lambda _prompt: "s")
    assert cli.main(["set-key", "eodhd"]) == 0
    assert keystore.load_key("eodhd", paths.secrets_path()) == "synthetic-key-value-2"
    assert KEY not in capsys.readouterr().out


def test_set_key_can_be_cancelled(terminal, monkeypatch, capsys):
    def interrupted(_prompt):
        raise KeyboardInterrupt

    monkeypatch.setattr(getpass, "getpass", interrupted)
    assert cli.main(["set-key", "eodhd"]) == 130
    assert not paths.secrets_path().exists()


def test_unknown_provider_is_a_usage_error():
    with pytest.raises(SystemExit) as code:
        cli.main(["set-key", "finnhub"])
    assert code.value.code == 2
