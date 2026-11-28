import subprocess

import next_version
import pytest


def test_a_tagged_version_gets_the_next_patch():
    assert next_version.next_version("0.3.0", tagged=True) == "0.3.1"
    assert next_version.next_version("0.4.9", tagged=True) == "0.4.10"


def test_an_untagged_version_is_released_as_it_is():
    assert next_version.next_version("0.4.0", tagged=False) == "0.4.0"


@pytest.mark.parametrize("version", ["0.3.0-dev", "0.3", "v0.3.0", "0.3.x"])
def test_a_version_that_is_not_three_numbers_is_refused(version):
    with pytest.raises(ValueError):
        next_version.next_version(version, tagged=True)


def test_is_tagged_reads_the_repository(tmp_path):
    def git(*args):
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "test@example.com")
    git("config", "user.name", "test")
    git("commit", "-q", "--allow-empty", "-m", "first")
    git("tag", "v1.0.0")
    assert next_version.is_tagged("1.0.0", tmp_path)
    assert not next_version.is_tagged("1.0.1", tmp_path)
