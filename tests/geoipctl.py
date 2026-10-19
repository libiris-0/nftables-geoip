"""Integration test of deploy/geoipctl in an unprivileged user and network namespace.

The test builds the test world, compiles examples/rules.txt and loads
examples/geomark.nft to define the three maps. A local HTTP server stands in for the
GitHub API and the release downloads. Each scenario checks the maps in the kernel,
the local copy and the recorded tag.
"""
from __future__ import annotations

import contextlib
import fcntl
import gzip
import http.server
import io
import json
import os
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

from nftables_geoip.cli import main as cli
from tests import world

ROOT = Path(__file__).resolve().parents[1]
GEOIPCTL = ROOT / "deploy/geoipctl"
TABLE = "inet routing"                       # the table of examples/geomark.nft
LATEST = "/repos/o/r/releases/latest"
TOKEN = "secret"


def isolate() -> None:
    uid, gid = os.getuid(), os.getgid()
    os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNET)
    Path("/proc/self/setgroups").write_text("deny")
    Path("/proc/self/uid_map").write_text(f"0 {uid} 1")
    Path("/proc/self/gid_map").write_text(f"0 {gid} 1")
    subprocess.run(["ip", "link", "set", "lo", "up"], check=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        self.server.auth.append(self.headers["Authorization"])
        if self.path == LATEST and self.server.latest is not None:
            body = json.dumps(self.server.latest).encode()
        elif self.path in self.server.assets:
            body = self.server.assets[self.path]
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args) -> None:
        pass


class Server(http.server.ThreadingHTTPServer):
    """The latest release, its assets, and the Authorization header of every request."""

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server_port}"
        self.latest: dict | None = None
        self.assets: dict[str, bytes] = {}
        self.auth: list[str | None] = []

    def release(self, tag: str, body: bytes, name: str = "home.nft.gz") -> None:
        path = f"/asset/{tag}"
        self.assets[path] = body
        self.latest = {"tag_name": tag, "assets": [{"name": name, "url": self.url + path}]}


class Checks:
    """Collect check results under the current group."""

    def __init__(self):
        self.cases: list[dict] = []
        self.current = ""

    def group(self, name: str) -> None:
        self.current = name

    def __call__(self, what: str, ok: bool) -> None:
        self.cases.append({"group": self.current, "name": what, "status": "pass" if ok else "fail"})


def compile_world(work: Path) -> Path:
    world.write_geoip(work / "geoip")
    world.write_links(work / "links.txt")
    script = work / "maps.nft"
    with contextlib.redirect_stderr(io.StringIO()):
        assert cli(["build", "--geoip", str(work / "geoip"), "--countries", "0x800-0xfff",
                    "--links", str(work / "links.txt"), "--out", str(work / "build")]) == 0
        assert cli(["compile", str(work / "build"), str(ROOT / "examples/rules.txt"),
                    "--table", TABLE, "-o", str(script)]) == 0
    return script


def nft(*args: str) -> str:
    return subprocess.run(["nft", *args], check=True, capture_output=True, text=True).stdout


def elements() -> int:
    items = json.loads(nft("-j", "list", "map", *TABLE.split(), "geo4"))["nftables"]
    return sum(len(i["map"].get("elem", [])) for i in items if "map" in i)


def run() -> list[dict]:
    isolate()
    work = Path(tempfile.mkdtemp(prefix="geoipctl-"))
    server = Server()
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        return scenarios(work, server)
    finally:
        server.shutdown()
        shutil.rmtree(work)


def scenarios(work: Path, server: Server) -> list[dict]:
    script = compile_world(work)
    nft("-f", str(ROOT / "examples/geomark.nft"))
    state, cred = work / "state", work / "cred"
    cred.mkdir()
    (cred / "token").write_text(TOKEN + "\n")
    env = os.environ | {"REPO": "o/r", "CONFIG": "home", "NFTABLES_GEOIP_STATE": str(state),
                        "NFTABLES_GEOIP_API": server.url, "CREDENTIALS_DIRECTORY": str(cred)}
    gz = gzip.compress(script.read_bytes(), mtime=0)
    check = Checks()

    def geoipctl(*args: str, environ: dict = env) -> int:
        return subprocess.run([GEOIPCTL, *args], env=environ, capture_output=True).returncode

    def tag() -> str | None:
        path = state / "tag"
        return path.read_text().strip() if path.exists() else None

    def clean() -> bool:
        return sorted(os.listdir(state)) == ["maps.nft", "tag"]

    check.group("命令行")
    check("没有子命令时以状态 2 退出", geoipctl() == 2)

    check.group("没有本地副本")
    check("没有本地副本时 restore 成功", geoipctl("restore") == 0)
    check("没有本地副本时 restore 不加载任何元素", elements() == 0)

    check.group("缺少 CONFIG")
    server.release("20261015T072301Z", gz)
    without_config = {k: v for k, v in env.items() if k != "CONFIG"}
    check("缺少 CONFIG 时 update 失败", geoipctl("update", environ=without_config) != 0)
    check("缺少 CONFIG 时不加载任何元素", elements() == 0)
    check("缺少 CONFIG 时不记录 tag", tag() is None)

    server.auth.clear()
    check.group("首次 update")
    check("首次 update 成功", geoipctl("update") == 0)
    want = elements()
    check("首次 update 加载了元素", want > 0)
    check("首次 update 记录了 tag", tag() == "20261015T072301Z")
    check("首次 update 保存了本地副本", (state / "maps.nft").read_bytes() == script.read_bytes())
    check("首次 update 没有残留临时文件", clean())
    check("每个请求都带 token", server.auth == [f"Bearer {TOKEN}"] * 2)

    check.group("已是最新")
    nft("flush", "map", *TABLE.split(), "geo4")
    check("tag 未变时 update 成功", geoipctl("update") == 0)
    check("tag 未变时不重新加载", elements() == 0)

    check.group("restore")
    check("restore 成功", geoipctl("restore") == 0)
    check("restore 加载本地副本", elements() == want)

    check.group("锁")
    nft("flush", "map", *TABLE.split(), "geo4")
    with open(GEOIPCTL) as held:
        fcntl.flock(held, fcntl.LOCK_EX)
        waiting = subprocess.Popen([GEOIPCTL, "restore"], env=env, stderr=subprocess.DEVNULL)
        time.sleep(1)
        check("另一个进程持有锁时 restore 等待", waiting.poll() is None and elements() == 0)
    check("锁释放后 restore 完成", waiting.wait() == 0 and elements() == want)

    def failure(what: str) -> None:
        check.group(f"失败：{what}")
        before = (state / "maps.nft").read_bytes()
        nft("flush", "map", *TABLE.split(), "geo4")
        nft("-f", str(script))
        check("update 失败", geoipctl("update") != 0)
        check("内核中的元素不变", elements() == want)
        check("本地副本不变", (state / "maps.nft").read_bytes() == before)
        check("tag 不变", tag() == "20261015T072301Z")
        check("没有残留临时文件", clean())

    server.release("20261016T072301Z", gz[:len(gz) // 2])
    failure("下载不完整")

    latest, server.latest = server.latest, None
    failure("查询 Release 失败")
    server.latest = latest

    server.release("20261017T072301Z", gz, name="office.nft.gz")
    failure("Release 中没有本机配置的文件")

    broken = script.read_text().replace("geo4", "nosuchmap")
    server.release("20261018T072301Z", gzip.compress(broken.encode(), mtime=0))
    failure("nft 无法加载")

    check.group("恢复")
    server.release("20261019T072301Z", gz)
    check("失败后再次 update 成功", geoipctl("update") == 0)
    check("失败后再次 update 记录新 tag", tag() == "20261019T072301Z")
    return check.cases
