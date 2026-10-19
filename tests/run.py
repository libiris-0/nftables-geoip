"""Run the test suites in parallel, each in its own process, and print a summary."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SUITES = ("unit", "geoipctl")


class Result(unittest.TestResult):
    """Record one status per test method; a failing subtest fails its method."""

    def __init__(self):
        super().__init__()
        self.cases: dict[str, dict] = {}

    def record(self, test, status: str, err=None) -> None:
        module = sys.modules[type(test).__module__]
        group = f"{module.__name__.removeprefix('tests.')}  {module.__doc__.splitlines()[0]}"
        name = test.id().removeprefix(module.__name__ + ".")
        case = self.cases.setdefault(test.id(), {"group": group, "name": name, "status": "pass"})
        if status != "pass" and case["status"] != "error":
            case["status"] = status
            first = str(err[1]).partition("\n")[0]
            case["message"] = f"{err[0].__name__}: {first}"

    def addSuccess(self, test):
        self.record(test, "pass")

    def addFailure(self, test, err):
        self.record(test, "fail", err)

    def addError(self, test, err):
        self.record(test, "error", err)

    def addSubTest(self, test, subtest, err):
        if err is not None:
            failed = issubclass(err[0], test.failureException)
            self.record(test, "fail" if failed else "error", err)


def unit() -> list[dict]:
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = Result()
    suite.run(result)
    return list(result.cases.values())


def geoipctl() -> list[dict]:
    from tests import geoipctl
    return geoipctl.run()


def child(name: str, output: Path) -> int:
    try:
        cases = {"unit": unit, "geoipctl": geoipctl}[name]()
        counts = {s: sum(c["status"] == s for c in cases) for s in ("pass", "fail", "error")}
        result = {"counts": counts, "cases": cases}
        (output / f"{name}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False))
        return int(bool(counts["fail"] or counts["error"]))
    except BaseException:
        traceback.print_exc()
        return 2


def summary(name: str, output: Path) -> str:
    path = output / f"{name}.json"
    if not path.exists():
        return f"{name}: no result"
    result = json.loads(path.read_text())
    lines = [f"{name}: " + " ".join(f"{k} {v}" for k, v in result["counts"].items())]
    group = None
    for case in result["cases"]:
        if case["group"] != group:
            group = case["group"]
            lines.append(f"  {group}")
        status = {"pass": "ok", "fail": "FAIL", "error": "ERROR"}[case["status"]]
        lines.append(f"    {status:<5} {case['name']}")
        if "message" in case:
            lines.append(f"          {case['message']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("suites", nargs="*", choices=SUITES, default=SUITES)
    parser.add_argument("--output", type=Path, help="new directory for the <suite>.json files")
    args = parser.parse_args()
    if args.output:
        args.output.mkdir(parents=True)
        output = args.output.resolve()
    else:
        output = Path(tempfile.mkdtemp(prefix="nftables-geoip-tests-"))
    print(f"Results: {output}", flush=True)
    children = {}
    for name in dict.fromkeys(args.suites):
        pid = os.fork()
        if pid == 0:
            os._exit(child(name, output))
        children[pid] = name
    status = 0
    while children:
        pid, code = os.wait()
        name = children.pop(pid)
        code = os.waitstatus_to_exitcode(code)
        status = max(status, code if code >= 0 else 2)
        print(summary(name, output), flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
