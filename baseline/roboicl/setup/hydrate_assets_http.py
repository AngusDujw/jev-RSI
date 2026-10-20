"""Hydrate Git-LFS assets via revision-pinned HTTPS resolve URLs.

Some mirrors serve resolve GETs but return unreachable signed LFS transfer URLs.
Expected SHA256 and sizes come from the checked-out Git blobs, not the mirror's
metadata API. The unchanged fetch_assets.py performs final checkout/fsck/setup.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(2**20), b""):
            value.update(chunk)
    return value.hexdigest()


def git(cache, *arguments, **kwargs):
    return subprocess.check_output(["git", "-C", str(cache), *arguments], **kwargs)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    parser.add_argument("--workers", type=int, default=16, choices=range(1, 33))
    parser.add_argument("--asset", help="Optional single-file transfer probe; does not install a complete tree")
    parser.add_argument("--seed-assets", type=Path, help="Read-only existing Assets tree; copy only frozen SHA256 matches")
    parser.add_argument("--seed-only", action="store_true", help="Verify/copy available assets without any network requests")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root/"configs/data.lock.json").read_text())["assets"]
    cache = args.cache.resolve()
    revision = git(cache, "rev-parse", "HEAD", text=True).strip()
    if revision != lock["revision"]:
        raise ValueError("Asset Git revision differs from the official lock")
    tree = git(cache, "ls-tree", "-r", "-z", "HEAD", "--", "Assets")
    rows = []
    for record in tree.split(b"\0"):
        if record:
            header, path = record.split(b"\t", 1)
            rows.append((header.split()[2].decode(), path.decode()))
    blobs = git(cache, "cat-file", "--batch", input=("\n".join(row[0] for row in rows)+"\n").encode())
    at = 0
    objects = {}
    file_bytes = 0
    for _, path in rows:
        end = blobs.index(b"\n", at)
        size = int(blobs[at:end].split()[2])
        blob = blobs[end+1:end+1+size]
        at = end+size+2
        match = re.fullmatch(rb"version https://git-lfs.github.com/spec/v1\noid sha256:([a-f0-9]{64})\nsize ([0-9]+)\n", blob)
        if not match or (args.asset and path != args.asset):
            continue
        oid, size = match[1].decode(), int(match[2])
        file_bytes += size
        objects.setdefault(oid, (path, size))
    if args.asset and not objects:
        raise ValueError("The requested asset is not a locked LFS file")
    if not args.asset and shutil.disk_usage(cache).free < sum(size for _, size in objects.values()) + file_bytes + 2**30:
        raise RuntimeError("Insufficient project-disk space for LFS objects plus checkout")
    print(json.dumps({"revision": revision, "unique_objects": len(objects), "checkout_bytes": file_bytes,
                      "endpoint": args.endpoint, "single_file_probe": bool(args.asset)}), flush=True)
    stop = threading.Event()
    progress = threading.Lock()
    counts = {"objects": 0, "bytes": 0, "last_print": 0.0}

    def fetch(item):
        if stop.is_set():
            return
        oid, (path, size) = item
        target = cache/".git/lfs/objects"/oid[:2]/oid[2:4]/oid
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.stat().st_size != size or digest(target) != oid:
                raise RuntimeError("Existing LFS object fails integrity: " + oid)
        else:
            part = target.with_suffix(".roboicl-part")
            if part.is_symlink():
                raise ValueError("Refuse a symlinked transfer scratch file")
            seed = args.seed_assets / Path(path).relative_to("Assets") if args.seed_assets else None
            try:
                seed_matches = seed is not None and seed.is_file() and seed.stat().st_size == size and digest(seed) == oid
            except OSError:
                # An unreadable optional seed is a cache miss, never a reason
                # to change another installation's permissions.
                seed_matches = False
            if seed_matches:
                # Copy, never hardlink: final materialization must not alter
                # an existing installation through a shared inode.
                shutil.copyfile(seed, part)
                if digest(part) != oid:
                    raise RuntimeError("Seed asset changed during copying: " + path)
                part.replace(target)
        if not target.exists():
            if args.seed_only:
                return
            url = args.endpoint.rstrip("/")+"/datasets/"+lock["repo_id"]+"/resolve/"+revision+"/"+urllib.parse.quote(path)
            for attempt in range(3):
                try:
                    request = urllib.request.Request(url+f"?download=true&roboicl_attempt={attempt}", headers={"User-Agent": "roboicl-reproduction/1.0"})
                    received = 0
                    value = hashlib.sha256()
                    with urllib.request.urlopen(request, timeout=40) as reply, part.open("wb") as stream:
                        while True:
                            chunk = reply.read(2**20)
                            if not chunk:
                                break
                            stream.write(chunk)
                            value.update(chunk)
                            received += len(chunk)
                            if received > size:
                                raise ValueError("Asset response exceeds the frozen byte size")
                    if received != size or value.hexdigest() != oid:
                        raise ValueError("Asset response fails frozen SHA256/size")
                    part.replace(target)
                    break
                except Exception:
                    if attempt == 2:
                        stop.set()
                        raise
                    time.sleep(1+attempt)
        with progress:
            counts["objects"] += 1
            counts["bytes"] += size
            if time.monotonic()-counts["last_print"] > 10 or counts["objects"] == len(objects):
                counts["last_print"] = time.monotonic()
                print(json.dumps({"verified_objects": counts["objects"], "total_objects": len(objects), "verified_bytes": counts["bytes"]}), flush=True)

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = [executor.submit(fetch, item) for item in objects.items()]
        for future in as_completed(futures):
            try:
                future.result()
            except Exception:
                stop.set()
                for pending in futures:
                    pending.cancel()
                raise
    print(json.dumps({"verified_objects": counts["objects"], "total_objects": len(objects),
                      "verified_bytes": counts["bytes"], "complete": counts["objects"] == len(objects)}), flush=True)
    if not args.seed_only:
        print("LFS objects verified. Run unchanged setup/fetch_assets.py to finalize.", flush=True)


if __name__ == "__main__":
    main()
