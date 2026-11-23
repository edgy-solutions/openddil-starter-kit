"""tools/new-algo-repo.sh, end to end, against a fake GitHub API on localhost.

Each test builds a small fake kit (a git repo with the real hooks, a .gitignore
and SHA256SUMS), serves a fake API whose repos are local bare repositories, and
runs the script under Git Bash (or bash elsewhere). Nothing touches the network.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tarfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[1]
KIT_ROOT = TOOLS.parent
SCRIPT = TOOLS / "new-algo-repo.sh"
TOKEN = "test-token-5f2c"


def _find_bash() -> str | None:
    if os.environ.get("NEW_ALGO_REPO_BASH"):
        return os.environ["NEW_ALGO_REPO_BASH"]
    if sys.platform == "win32":
        # Not System32\bash.exe (WSL): Git for Windows' own bash.
        git = shutil.which("git")
        if not git:
            return None
        for up in (1, 2, 3):
            cand = Path(git).resolve().parents[up] / "bin" / "bash.exe"
            if cand.exists():
                return str(cand)
        return None
    return shutil.which("bash")


BASH = _find_bash()
pytestmark = pytest.mark.skipif(BASH is None, reason="no bash to run the script with")


def _git(*args, cwd=None, env=None) -> str:
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True,
                          capture_output=True, text=True).stdout.strip()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _tar(members: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=tarfile.USTAR_FORMAT) as t:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            info.mtime = 0
            t.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _sums(tars: dict[str, bytes], inner: dict[str, bytes]) -> str:
    lines = [f"{_sha(b)} *{n}" for n, b in {**tars, **inner}.items()]
    return "\n".join(lines) + "\n"


class Fake:
    """The fake API's state, shared with its handler."""

    def __init__(self, root: Path):
        self.root = root
        self.login = "alice"
        self.orgs = {"lab-org"}
        self.repos: dict[tuple[str, str], dict] = {}
        self.requests: list[dict] = []
        self.force_public = False
        self.tag = "recording-rev30"
        self.assets: dict[str, bytes] = {}
        self.base = ""

    def repo_json(self, owner, name):
        r = self.repos[(owner, name)]
        return {"full_name": f"{owner}/{name}", "private": r["private"],
                "visibility": "private" if r["private"] else "public",
                "clone_url": r["bare"].as_uri(),
                "html_url": f"https://example.test/{owner}/{name}"}

    def create(self, owner, name, private) -> Path:
        bare = self.root / "remotes" / owner / f"{name}.git"
        bare.parent.mkdir(parents=True, exist_ok=True)
        _git("init", "-q", "--bare", str(bare))
        self.repos[(owner, name)] = {"private": private, "bare": bare}
        return bare


def _handler(fake: Fake):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # quiet
            pass

        def _send(self, code, obj=None, raw=None):
            body = raw if raw is not None else json.dumps(obj or {}).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _record(self, body=None):
            fake.requests.append({"method": self.command, "path": self.path,
                                  "host": self.headers.get("Host", ""),
                                  "auth": self.headers.get("Authorization"),
                                  "body": body})

        def do_GET(self):
            self._record()
            parts = [p for p in self.path.split("/") if p]
            if parts[:1] == ["dl"] and len(parts) == 2 and parts[1] in fake.assets:
                return self._send(200, raw=fake.assets[parts[1]])
            if parts[:4] == ["repos", "kit", "kit", "releases"] and len(parts) == 6:
                if parts[5] != fake.tag:
                    return self._send(404, {"message": "Not Found"})
                return self._send(200, {"tag_name": fake.tag, "assets": [
                    {"name": n, "browser_download_url": f"{fake.base}/dl/{n}"}
                    for n in fake.assets]})
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401, {"message": "Bad credentials"})
            if parts == ["user"]:
                return self._send(200, {"login": fake.login})
            if parts[:1] == ["repos"] and len(parts) == 3:
                key = (parts[1], parts[2])
                if key not in fake.repos:
                    return self._send(404, {"message": "Not Found"})
                return self._send(200, fake.repo_json(*key))
            return self._send(404, {"message": "Not Found"})

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            self._record(body)
            if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                return self._send(401, {"message": "Bad credentials"})
            parts = [p for p in self.path.split("/") if p]
            if parts == ["user", "repos"]:
                owner = fake.login
            elif parts[:1] == ["orgs"] and len(parts) == 3 and parts[2] == "repos":
                owner = parts[1]
                if owner not in fake.orgs:
                    return self._send(404, {"message": "Not Found"})
            else:
                return self._send(404, {"message": "Not Found"})
            name = body["name"]
            if (owner, name) in fake.repos:
                return self._send(422, {"message": "name already exists on this account"})
            fake.create(owner, name, bool(body.get("private")) and not fake.force_public)
            return self._send(201, fake.repo_json(owner, name))
    return H


INNER = {"data/edge-01/raw-sensor-stream.1-2.gz": b"edge one bytes",
         "data/edge-02/raw-sensor-stream.1-2.gz": b"edge two bytes"}


@pytest.fixture
def rig(tmp_path):
    fake = Fake(tmp_path)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _handler(fake))
    port = srv.server_address[1]
    fake.base = f"http://localhost:{port}"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    home = tmp_path / "home"
    home.mkdir()
    env = {k: v for k, v in os.environ.items()
           if k not in ("GITHUB_TOKEN", "GH_TOKEN", "GIT_ASKPASS", "SSH_ASKPASS")}
    env.update({"HOME": str(home), "USERPROFILE": str(home), "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_TERMINAL_PROMPT": "0", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.test",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.test",
                "GITHUB_TOKEN": TOKEN, "PYTHON": sys.executable.replace("\\", "/")})
    env.pop("MSYS_NO_PATHCONV", None)

    tars = {"data-edge-01.tar": _tar({k: v for k, v in INNER.items() if "edge-01" in k}),
            "data-edge-02.tar": _tar({k: v for k, v in INNER.items() if "edge-02" in k})}
    fake.assets.update(tars)

    kit = tmp_path / "kit"
    (kit / "tools").mkdir(parents=True)
    shutil.copytree(TOOLS / "hooks", kit / "tools" / "hooks")
    shutil.copy(KIT_ROOT / ".gitignore", kit / ".gitignore")
    (kit / "SHA256SUMS").write_text(_sums(tars, INNER), newline="\n")
    (kit / "requirements.txt").write_text("", newline="\n")
    _git("init", "-q", "-b", "main", str(kit), env=env)
    _git("add", "-A", cwd=kit, env=env)
    _git("commit", "-q", "-m", "fake kit", cwd=kit, env=env)

    work = tmp_path / "work"
    work.mkdir()
    yield {"fake": fake, "env": env, "kit": kit, "work": work, "port": port, "tars": tars, "srv": srv}
    srv.shutdown()


def _run(rig, *args, env=None):
    fake = rig["fake"]
    api = f"http://127.0.0.1:{rig['port']}"
    cmd = [BASH, str(SCRIPT).replace("\\", "/"), "--api-url", api,
           "--kit-url", rig["kit"].as_uri(), "--kit-api", fake.base, "--kit-repo", "kit/kit",
           "--no-venv", *args]
    return subprocess.run(cmd, cwd=rig["work"], env=env or rig["env"], capture_output=True,
                          text=True, timeout=180)


def _heads(bare: Path) -> str:
    return _git("--git-dir", str(bare), "for-each-ref", "--format=%(refname) %(objectname)")


def test_user_repo_is_created_private_pushed_and_seeded(rig):
    r = _run(rig, "alice/algos")
    assert r.returncode == 0, r.stderr
    fake = rig["fake"]
    posts = [q for q in fake.requests if q["method"] == "POST"]
    assert [q["path"] for q in posts] == ["/user/repos"]
    assert posts[0]["body"]["private"] is True and posts[0]["body"]["name"] == "algos"

    kit_head = _git("rev-parse", "HEAD", cwd=rig["kit"])
    assert _heads(fake.repos[("alice", "algos")]["bare"]) == f"refs/heads/main {kit_head}"

    co = rig["work"] / "algos"
    assert _git("remote", "get-url", "--push", "upstream", cwd=co) == "DISABLED"
    clone_url = fake.repo_json("alice", "algos")["clone_url"]
    assert _git("remote", "get-url", "origin", cwd=co) == clone_url
    allowed = (co / ".git" / "info" / "allowed-remotes").read_text()
    assert clone_url in allowed.splitlines()
    assert (co / ".git" / "hooks" / "pre-push").exists()

    for path, data in INNER.items():
        assert (co / path).read_bytes() == data
    assert not list(co.glob("*.tar"))
    assert _git("status", "--porcelain", cwd=co) == ""        # data/ stays out of git

    api_reqs = [q for q in fake.requests if q["host"].startswith("127.0.0.1")]
    assert api_reqs and all(q["auth"] == f"Bearer {TOKEN}" for q in api_reqs)
    kit_reqs = [q for q in fake.requests if q["host"].startswith("localhost")]
    assert kit_reqs and all(q["auth"] is None for q in kit_reqs)   # no token to another host
    assert TOKEN not in r.stdout + r.stderr
    assert "Done. Private repo: https://example.test/alice/algos" in r.stdout


def test_push_to_the_public_kit_is_refused(rig):
    assert _run(rig, "alice/algos").returncode == 0
    co = rig["work"] / "algos"
    p = subprocess.run(["git", "push", "upstream", "main"], cwd=co, env=rig["env"],
                       capture_output=True, text=True)
    assert p.returncode != 0
    other = rig["work"] / "other.git"
    _git("init", "-q", "--bare", str(other))
    _git("remote", "add", "elsewhere", other.as_uri(), cwd=co)
    p = subprocess.run(["git", "push", "elsewhere", "main"], cwd=co, env=rig["env"],
                       capture_output=True, text=True)
    assert p.returncode != 0 and "remote-not-allowed" in p.stderr
    assert _heads(other) == ""


def test_org_repo_is_created_in_the_org(rig):
    r = _run(rig, "lab-org/algos")
    assert r.returncode == 0, r.stderr
    assert [q["path"] for q in rig["fake"].requests if q["method"] == "POST"] == ["/orgs/lab-org/repos"]


def test_unknown_owner_is_refused(rig):
    r = _run(rig, "nobody/algos")
    assert r.returncode == 1
    assert "neither alice nor an organization" in r.stderr
    assert not (rig["work"] / "algos").exists()


def test_a_repo_that_reads_back_public_is_never_pushed(rig):
    rig["fake"].force_public = True
    r = _run(rig, "alice/algos")
    assert r.returncode == 1
    assert "STOP" in r.stderr and "Nothing was pushed" in r.stderr
    assert _heads(rig["fake"].repos[("alice", "algos")]["bare"]) == ""
    assert not (rig["work"] / "algos").exists()


def test_existing_name_suggests_use_existing(rig):
    rig["fake"].create("alice", "algos", True)
    r = _run(rig, "alice/algos")
    assert r.returncode == 1 and "--use-existing" in r.stderr


def test_use_existing_seeds_an_empty_private_repo(rig):
    bare = rig["fake"].create("alice", "algos", True)
    r = _run(rig, "--use-existing", "alice/algos")
    assert r.returncode == 0, r.stderr
    assert not [q for q in rig["fake"].requests if q["method"] == "POST"]
    assert _heads(bare).startswith("refs/heads/main ")


def test_use_existing_refuses_a_repo_with_branches(rig):
    bare = rig["fake"].create("alice", "algos", True)
    seed = rig["work"] / "seed"
    _git("clone", "-q", str(rig["kit"]), str(seed), env=rig["env"])
    _git("push", "-q", bare.as_uri(), "main", cwd=seed, env=rig["env"])
    before = _heads(bare)
    r = _run(rig, "--use-existing", "--dir", "co", "alice/algos")
    assert r.returncode == 1 and "already has branches" in r.stderr
    assert _heads(bare) == before


def test_use_existing_refuses_a_public_repo(rig):
    rig["fake"].create("alice", "algos", False)
    r = _run(rig, "--use-existing", "alice/algos")
    assert r.returncode == 1 and "STOP" in r.stderr


def test_existing_folder_is_refused_before_any_api_call(rig):
    (rig["work"] / "algos").mkdir()
    r = _run(rig, "alice/algos")
    assert r.returncode == 1 and "already exists here" in r.stderr
    assert rig["fake"].requests == []


def test_no_token_is_refused(rig):
    env = dict(rig["env"])
    env.pop("GITHUB_TOKEN")
    r = _run(rig, "alice/algos", env=env)
    assert r.returncode == 1 and "no token for github.com" in r.stderr
    assert rig["fake"].requests == []


def test_bad_token_is_refused(rig):
    env = dict(rig["env"], GITHUB_TOKEN="wrong")
    r = _run(rig, "alice/algos", env=env)
    assert r.returncode == 1 and "HTTP 401" in r.stderr
    assert "wrong" not in r.stdout


def test_a_checksum_mismatch_stops(rig):
    rig["fake"].assets["data-edge-02.tar"] = _tar({"data/edge-02/raw-sensor-stream.1-2.gz": b"tampered"})
    r = _run(rig, "alice/algos")
    assert r.returncode == 1
    assert "STOP: the recording doesn't match" in r.stderr
    assert "stopped at: fetch and check recording" in r.stderr or "STOP" in r.stderr


def test_a_release_with_its_own_sums_is_checked_against_them(rig):
    fake = rig["fake"]
    new_inner = {"data/edge-01/raw-sensor-stream.3-4.gz": b"a later recording"}
    new_tar = {"data-edge-01.tar": _tar(new_inner)}
    fake.assets.clear()
    fake.assets.update(new_tar)
    fake.assets["SHA256SUMS"] = _sums(new_tar, new_inner).encode()
    fake.tag = "recording-rev31"
    r = _run(rig, "--recording", "recording-rev31", "alice/algos")
    assert r.returncode == 0, r.stderr
    co = rig["work"] / "algos"
    assert (co / "data/edge-01/raw-sensor-stream.3-4.gz").exists()
    assert not (co / "SHA256SUMS.recording").exists()
    assert _git("status", "--porcelain", cwd=co) == ""


def test_an_unknown_recording_tag_is_refused(rig):
    r = _run(rig, "--recording", "recording-rev99", "alice/algos")
    assert r.returncode == 1 and "release recording-rev99" in r.stderr


def test_recording_from_a_folder_needs_no_network(rig):
    src = rig["work"] / "downloads"
    src.mkdir()
    for n, b in rig["tars"].items():
        (src / n).write_bytes(b)
    rig["fake"].assets.clear()
    r = _run(rig, "--recording-from", str(src).replace("\\", "/"), "alice/algos")
    assert r.returncode == 0, r.stderr
    assert not [q for q in rig["fake"].requests if "/releases/" in q["path"] or q["path"].startswith("/dl/")]
    assert (rig["work"] / "algos" / "data/edge-02/raw-sensor-stream.1-2.gz").exists()


def test_no_recording_skips_the_data(rig):
    r = _run(rig, "--no-recording", "alice/algos")
    assert r.returncode == 0, r.stderr
    assert not (rig["work"] / "algos" / "data").exists()


def test_enterprise_host_names_the_api_by_default(rig):
    # Without --api-url, a non-github.com host means https://HOST/api/v3.
    fake = rig["fake"]
    cmd = [BASH, str(SCRIPT).replace("\\", "/"), "--host", "127.0.0.1:1", "--no-venv",
           "--kit-url", rig["kit"].as_uri(), "alice/algos"]
    r = subprocess.run(cmd, cwd=rig["work"], env=rig["env"], capture_output=True, text=True, timeout=60)
    assert r.returncode == 1 and "https://127.0.0.1:1/api/v3" in r.stderr
    assert fake.requests == []


@pytest.mark.parametrize("target", ["algos", "a/b/c", "/algos", "alice/", "al ice/algos"])
def test_bad_targets_are_refused(rig, target):
    r = _run(rig, target)
    assert r.returncode in (1, 2)
    assert rig["fake"].requests == []


@pytest.mark.skipif(os.environ.get("NEW_ALGO_REPO_LIVE") != "1",
                    reason="set NEW_ALGO_REPO_LIVE=1 to clone the real kit and download the real recording (~210 MB)")
def test_live_kit_and_recording(rig):
    """The real kit's history through the private-mode hooks, and the real release through sha256sum."""
    api = f"http://127.0.0.1:{rig['port']}"
    cmd = [BASH, str(SCRIPT).replace("\\", "/"), "--api-url", api, "--no-venv", "alice/algos"]
    r = subprocess.run(cmd, cwd=rig["work"], env=rig["env"], capture_output=True, text=True, timeout=1800)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    co = rig["work"] / "algos"
    bare = rig["fake"].repos[("alice", "algos")]["bare"]
    assert _heads(bare) == f"refs/heads/main {_git('rev-parse', 'HEAD', cwd=co)}"
    sums = (co / "SHA256SUMS").read_text().splitlines()
    files = [ln.split(" ", 1)[1].lstrip("*") for ln in sums if ln.strip() and not ln.rstrip().endswith(".tar")]
    assert files and all((co / f).is_file() for f in files)
    assert not list(co.glob("*.tar"))
    assert _git("status", "--porcelain", cwd=co) == ""
