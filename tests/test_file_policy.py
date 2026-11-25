"""file_policy: docs/handoff-file-preview.md §4, rules 2-6 and the deny list (temporary paths only)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import file_policy


@pytest.fixture
def places(tmp_path):
    root = tmp_path
    home = root / "home"
    data = root / "data"
    for folder in (home, data):
        folder.mkdir(parents=True, exist_ok=True)
    options = {"drives": [root.anchor], "home": str(home), "data": str(data)}
    return root, home, data, options


def make(root: Path, name: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture", encoding="utf-8")
    return path


def test_allows_a_regular_file_and_returns_its_stat(places):
    root, _, _, options = places
    path = make(root, "answer/fig.png")
    assert file_policy.check(path, **options) is None
    reason, st = file_policy.inspect(path, **options)
    assert reason is None
    assert st.st_size == path.stat().st_size


def test_missing_and_folder(places):
    root, _, _, options = places
    assert file_policy.check(root / "gone.txt", **options) == "missing"
    folder = root / "folder"
    folder.mkdir()
    assert file_policy.check(folder, **options) == "folder"


def test_network_and_foreign_paths_never_get_stat(places):
    root, _, _, options = places
    calls = []

    def guard(path):
        calls.append(path)
        raise AssertionError(path)

    for path in (r"\\server\share\a.txt", "//server/share/a.txt", "/home/me/a.txt",
                 "/tmp/a.txt", r"Z:\outside\a.txt"):
        assert file_policy.check(path, stat=guard, **options) == "not_local", path
    assert calls == []


@pytest.mark.parametrize("relative", [
    "remote_config.json", "nested/remote_config.json",
    ".env", ".env.local", ".env.production",
    "id_rsa", "id_rsa.pub", "id_ed25519", "id_ed25519_sk",
    "server.pem", "server.key", "bundle.p12", "bundle.pfx", "store.jks", "store.keystore", "vault.kdbx",
    "CON.txt", "aux", "COM1.log",
])
def test_denied_names(places, relative):
    root, _, _, options = places
    assert file_policy.check(root / relative, **options) == "denied"


def test_env_examples_are_not_denied(places):
    root, _, _, options = places
    for name in (".env.example", ".env.sample", "notes.txt"):
        path = make(root, name)
        assert file_policy.check(path, **options) is None


@pytest.mark.parametrize("relative", [
    "data/private.txt", "data/cache/thumb.png",
    "home/.ssh/id_rsa", "home/.gnupg/secring.gpg", "home/.aws/credentials",
    "home/.gemini/oauth_creds.json", "home/.config/gh/hosts.yml",
    "home/.codex/auth.json", "home/.claude/.credentials.json",
    "home/.dsh/.credentials.yaml", "home/.kube/config", "home/.docker/config.json",
    "home/.git-credentials", "home/.npmrc", "home/.pypirc",
    "home/.teleply-updates/update.exe", "home/.android/teleply-signing/key.jks",
    "Windows/System32/config/SAM",
    "AppData/Roaming/Microsoft/Credentials/abc",
    "AppData/Local/Microsoft/Protect/abc",
    "AppData/Local/Google/Chrome/User Data/Default/Login Data",
    "AppData/Local/Google/Chrome/User Data/Default/Cookies",
    "AppData/Local/Google/Chrome/User Data/Local State",
])
def test_denied_places(places, relative):
    root, _, _, options = places
    assert file_policy.check(root / relative, **options) == "denied"


def test_alternate_data_stream_and_nul(places):
    root, _, _, options = places
    allowed = make(root, "ok.txt")
    assert file_policy.check(str(allowed) + ":secret", **options) == "denied"
    assert file_policy.check(str(allowed) + "\x00.txt", **options) == "denied"


def test_a_long_local_path_is_still_local(places):
    root, _, _, options = places
    path = make(root, "long.txt")
    assert file_policy.check("\\\\?\\" + str(path), **options) is None


def test_a_link_is_not_followed(places):
    root, _, _, options = places
    real = make(root, "real.txt")
    link = root / "link.txt"
    try:
        link.symlink_to(real)
    except OSError:
        pytest.skip("Windows did not allow a symlink")
    assert file_policy.check(link, **options) == "denied"


def test_drive_list_is_injected(places):
    root, _, _, options = places
    path = make(root, "a.txt")
    options = dict(options, drives=["D:\\"])
    if root.anchor.upper() == "D:\\":
        assert file_policy.check(path, **options) is None
    else:
        assert file_policy.check(path, **options) == "not_local"
