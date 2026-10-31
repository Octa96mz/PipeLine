import stat

import pytest

from pipeline import keystore
from pipeline.errors import KeystoreError

KEY = "synthetic-key-value-1"


@pytest.fixture
def path(tmp_path):
    return tmp_path / "config" / "pipeline" / "secrets.toml"


def test_saved_key_is_private_and_readable(path):
    keystore.save_key("eodhd", KEY, path)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert keystore.load_key("eodhd", path) == KEY
    assert keystore.has_key("eodhd", path)


def test_no_temporary_files_remain(path):
    keystore.save_key("eodhd", KEY, path)
    assert [item.name for item in path.parent.iterdir()] == ["secrets.toml"]


def test_saving_one_provider_preserves_the_other(path):
    keystore.save_key("eodhd", KEY, path)
    keystore.save_key("coingecko", "synthetic-key-value-2", path)
    assert keystore.load_key("eodhd", path) == KEY
    assert keystore.load_key("coingecko", path) == "synthetic-key-value-2"


def test_saving_replaces_the_previous_key(path):
    keystore.save_key("eodhd", KEY, path)
    keystore.save_key("eodhd", "synthetic-key-value-2", path)
    assert keystore.load_key("eodhd", path) == "synthetic-key-value-2"


def test_missing_file_means_no_key(path):
    assert keystore.load_key("eodhd", path) is None
    assert not keystore.has_key("eodhd", path)


def test_environment_variable_takes_priority(path, monkeypatch):
    keystore.save_key("eodhd", KEY, path)
    monkeypatch.setenv("PIPELINE_EODHD_API_KEY", "synthetic-from-env")
    assert keystore.load_key("eodhd", path) == "synthetic-from-env"


@pytest.mark.parametrize("mode", [0o640, 0o604, 0o644])
def test_insecure_permissions_are_refused(path, mode):
    keystore.save_key("eodhd", KEY, path)
    path.chmod(mode)
    with pytest.raises(KeystoreError, match="permisos inseguros") as error:
        keystore.load_key("eodhd", path)
    assert KEY not in str(error.value)


def test_symlink_is_refused(path, tmp_path):
    keystore.save_key("eodhd", KEY, path)
    target = tmp_path / "elsewhere.toml"
    path.rename(target)
    path.symlink_to(target)
    with pytest.raises(KeystoreError):
        keystore.load_key("eodhd", path)


def test_malformed_file_does_not_leak_its_content(path):
    path.parent.mkdir(parents=True)
    path.write_text(f'[keys\neodhd = "{KEY}"\n', encoding="utf-8")
    path.chmod(0o600)
    with pytest.raises(KeystoreError) as error:
        keystore.load_key("eodhd", path)
    assert KEY not in str(error.value)
    assert error.value.__cause__ is None


@pytest.mark.parametrize(
    "bad_key", ["", "short", 'with"quote-value', "with space value", "line\nbreak-value", "x" * 513]
)
def test_invalid_key_is_refused_without_echoing_it(path, bad_key):
    with pytest.raises(KeystoreError) as error:
        keystore.save_key("eodhd", bad_key, path)
    assert "formato" in str(error.value)
    assert not bad_key or bad_key not in str(error.value)
    assert not path.exists()


def test_unknown_provider_is_refused(path):
    with pytest.raises(KeystoreError, match="desconocido"):
        keystore.save_key("nope", KEY, path)
