"""Fetch clean, exact upstream repositories for a vendored RoboICL checkout."""
import json
from pathlib import Path
import subprocess


def main():
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root / "configs/upstream.lock.json").read_text())
    for package in lock["packages"]:
        target = root / package["path"]
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init", str(target)], check=True)
            subprocess.run(["git", "-C", str(target), "remote", "add", "origin", package["url"]], check=True)
        actual = subprocess.run(["git", "-C", str(target), "rev-parse", "HEAD"], capture_output=True, text=True)
        if actual.returncode == 0 and actual.stdout.strip() != package["commit"]:
            raise RuntimeError(f"Existing checkout has a different revision: {target}")
        if actual.returncode:
            subprocess.run(["git", "-C", str(target), "fetch", "--depth", "1", "origin", package["commit"]], check=True)
            subprocess.run(["git", "-C", str(target), "checkout", "--detach", "FETCH_HEAD"], check=True)
        dirty = subprocess.check_output(["git", "-C", str(target), "status", "--porcelain"], text=True)
        if dirty.strip():
            raise RuntimeError(f"Existing checkout is dirty: {target}")
        print(package["name"], package["commit"], flush=True)


if __name__ == "__main__":
    main()
