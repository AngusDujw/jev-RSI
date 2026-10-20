"""Hydrate Git-LFS assets via revision-pinned HTTPS resolve URLs.

Some mirrors serve resolve GETs but return unreachable signed LFS transfer URLs.
Expected SHA256 and sizes come from the checked-out Git blobs, not the mirror's
metadata API. The unchanged fetch_assets.py performs final checkout/fsck/setup.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
import urllib.parse
import urllib.request
import urllib.error


def digest(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(2**20), b""):
            value.update(chunk)
    return value.hexdigest()


def git(cache, *arguments, **kwargs):
    return subprocess.check_output(["git", "-C", str(cache), *arguments], **kwargs)


def locked_asset_entries(cache, tasks=()):
    tree = git(cache, "ls-tree", "-r", "-z", "HEAD", "--", "Assets")
    rows = []
    layouts = {f"Assets/Eval_Layout/RoboDojo/arx_x5/0/{task}_{layout}.json"
               for task in tasks for layout in range(4)}
    for record in tree.split(b"\0"):
        if record:
            header, raw_path = record.split(b"\t", 1)
            path = raw_path.decode()
            if tasks and path.startswith("Assets/Eval_Layout/") and path not in layouts:
                continue
            rows.append((header.split()[2].decode(), path))
    if layouts - {path for _, path in rows}:
        raise ValueError("Requested task/layout is absent from the frozen Git tree")
    blobs = git(cache, "cat-file", "--batch", input=("\n".join(row[0] for row in rows)+"\n").encode())
    at = 0
    entries = []
    for _, path in rows:
        end = blobs.index(b"\n", at)
        size = int(blobs[at:end].split()[2])
        blob = blobs[end+1:end+1+size]
        at = end+size+2
        match = re.fullmatch(rb"version https://git-lfs.github.com/spec/v1\noid sha256:([a-f0-9]{64})\nsize ([0-9]+)\n", blob)
        entries.append({"path": path, "sha256": match[1].decode() if match else hashlib.sha256(blob).hexdigest(),
                        "size": int(match[2]) if match else size, "lfs": bool(match)})
    return entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--endpoint", default="https://hf-mirror.com")
    parser.add_argument("--workers", type=int, default=16, choices=range(1, 33))
    parser.add_argument("--asset", help="Optional single-file transfer probe; does not install a complete tree")
    parser.add_argument("--seed-assets", type=Path, help="Read-only existing Assets tree; copy only frozen SHA256 matches")
    parser.add_argument("--seed-only", action="store_true", help="Verify/copy available assets without any network requests")
    parser.add_argument("--inventory", action="store_true", help="Report missing cached objects without downloading")
    parser.add_argument("--seed-by-digest", action="store_true", help="Read-only scan of seed tree for matching objects under different paths; no network")
    parser.add_argument("--task", action="append", default=[], help="Keep the complete non-layout tree plus this task's seed-0 layouts 0..3")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root/"configs/data.lock.json").read_text())["assets"]
    cache = args.cache.resolve()
    revision = git(cache, "rev-parse", "HEAD", text=True).strip()
    if revision != lock["revision"]:
        raise ValueError("Asset Git revision differs from the official lock")
    objects = {}
    file_bytes = 0
    for entry in locked_asset_entries(cache, args.task):
        path = entry["path"]
        if not entry["lfs"] or (args.asset and path != args.asset):
            continue
        oid, size = entry["sha256"], entry["size"]
        file_bytes += size
        objects.setdefault(oid, (path, size))
    if args.asset and not objects:
        raise ValueError("The requested asset is not a locked LFS file")
    if args.seed_by_digest:
        if args.seed_assets is None:
            parser.error("--seed-by-digest requires --seed-assets")
        needed = {}
        for oid, (_, size) in objects.items():
            target = cache/".git/lfs/objects"/oid[:2]/oid[2:4]/oid
            if not target.is_file() or target.stat().st_size != size:
                needed.setdefault(size, set()).add(oid)
        copied = copied_bytes = unreadable = 0
        last_print = time.monotonic()
        for directory, _, names in os.walk(args.seed_assets, followlinks=False):
            for name in names:
                source = Path(directory)/name
                try:
                    if source.is_symlink() or source.stat().st_size not in needed:
                        continue
                    oid = digest(source)
                    size = source.stat().st_size
                    if oid not in needed.get(size, set()):
                        continue
                    target = cache/".git/lfs/objects"/oid[:2]/oid[2:4]/oid
                    target.parent.mkdir(parents=True, exist_ok=True)
                    part = target.with_suffix(".seed-part")
                    if part.is_symlink():
                        raise ValueError("Refuse symlinked seed scratch")
                    shutil.copyfile(source, part)
                    if part.stat().st_size != size or digest(part) != oid:
                        raise ValueError("Seed changed during copying")
                    part.replace(target)
                    needed[size].remove(oid)
                    copied += 1
                    copied_bytes += size
                except OSError:
                    unreadable += 1
                if time.monotonic()-last_print > 10:
                    print(json.dumps({"seed_objects_copied": copied, "seed_bytes_copied": copied_bytes}), flush=True)
                    last_print = time.monotonic()
        print(json.dumps({"seed_objects_copied": copied, "seed_bytes_copied": copied_bytes,
                          "unreadable_seed_files": unreadable, "network_requests": 0}), flush=True)
        return
    if args.inventory:
        missing, missing_bytes = Counter(), Counter()
        for oid, (path, size) in objects.items():
            target = cache/".git/lfs/objects"/oid[:2]/oid[2:4]/oid
            if not target.is_file() or target.stat().st_size != size:
                group = path.split("/")[1]
                missing[group] += 1
                missing_bytes[group] += size
        print(json.dumps({"missing_objects": dict(missing), "missing_bytes": dict(missing_bytes)}), flush=True)
        return
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
                except Exception as error:
                    if attempt == 2:
                        stop.set()
                        raise
                    time.sleep(30 if isinstance(error, urllib.error.HTTPError) and error.code in (429, 503) else 1+attempt)
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
        print("LFS objects verified. Finalize the complete tree with fetch_assets.py or a selected-layout tree with install_selected_assets.py.", flush=True)


if __name__ == "__main__":
    main()
