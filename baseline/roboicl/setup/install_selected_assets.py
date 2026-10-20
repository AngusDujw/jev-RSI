"""Install all frozen physical assets and exact selected evaluation layouts.

Uses the release's existing explicit-files manifest contract. Only unrelated
layout JSON files are excluded; every non-layout file remains mandatory.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from fetch_assets import materialize_robot_configs
from hydrate_assets_http import digest, git, locked_asset_entries


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--data-root", type=Path, required=True)
    parser.add_argument("--task", action="append", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    lock = json.loads((root/"configs/data.lock.json").read_text())["assets"]
    cache = args.cache.resolve()
    if git(cache, "rev-parse", "HEAD", text=True).strip() != lock["revision"]:
        raise ValueError("Asset revision differs from the official lock")
    entries = locked_asset_entries(cache, args.task)
    subprocess.run(["git", "-C", str(cache), "lfs", "checkout"], check=True)
    for entry in entries:
        path = cache/entry["path"]
        if not path.is_file() or path.stat().st_size != entry["size"] or digest(path) != entry["sha256"]:
            raise ValueError("Missing or changed frozen asset: " + entry["path"])
    data = args.data_root.resolve()
    data.mkdir(parents=True, exist_ok=True)
    target = data/"Assets"
    if target.exists() or target.is_symlink():
        if not target.is_symlink() or target.resolve() != (cache/"Assets").resolve():
            raise ValueError("Existing Assets target preserved")
    else:
        target.symlink_to(cache/"Assets", target_is_directory=True)
    generated = materialize_robot_configs(data)
    for entry in entries:
        if entry["path"] in generated:
            path = data/entry["path"]
            entry.update(source_sha256=entry["sha256"], sha256=digest(path), size=path.stat().st_size)
    tree = git(cache, "ls-tree", "-r", "HEAD", "Assets")
    manifest = {"schema": "roboicl.assets.install.v1", "repo_id": lock["repo_id"],
                "revision": lock["revision"], "scope": "explicit-files", "files": entries,
                "assets_tree_sha256": hashlib.sha256(tree).hexdigest(), "generated": generated,
                "selection": {"complete_non_layout_tree": True, "tasks": args.task, "seed": 0, "layouts": [0, 1, 2, 3]}}
    staged = data/".roboicl-assets.json.writing"
    staged.write_text(json.dumps(manifest, indent=2)+"\n")
    staged.replace(data/".roboicl-assets.json")
    print(json.dumps({"verified_files": len(entries), "verified_bytes": sum(row["size"] for row in entries),
                      "manifest": str(data/".roboicl-assets.json"), "selection": manifest["selection"]}))


if __name__ == "__main__":
    main()
