#!/usr/bin/env python3
"""Stream the pinned official SAM3 checkpoint using the local HF login.

--stdout supports an SSH asset transfer without copying the HF credential or
staging a second multi-GB checkpoint on the workstation. Metadata and checksum
are verified before/after streaming. The receiver must verify SHA256 before
promoting its partial file.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

REV = "3c879f39826c281e95690f02c7821c4de09afae7"
SHA = "9999e2341ceef5e136daa386eecb55cb414446a00ac2b55eb2dfd2f7c3cf8c9e"
SIZE = 3450062241


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stdout", action="store_true")
    p.add_argument("--output", type=Path)
    args = p.parse_args()
    if args.stdout == bool(args.output):
        p.error("Choose exactly one of --stdout or --output")
    import requests
    from huggingface_hub import get_hf_file_metadata, get_token, hf_hub_url
    url = hf_hub_url("facebook/sam3", "sam3.pt", revision=REV)
    token = get_token()
    meta = get_hf_file_metadata(url, token=token, timeout=30)
    if meta.size != SIZE or meta.etag.strip('"') != SHA:
        raise ValueError("Official checkpoint metadata differs from the audited pin")
    if args.output and args.output.exists():
        raise ValueError("Output exists; do not overwrite a checkpoint")
    stream = sys.stdout.buffer if args.stdout else args.output.open("xb")
    digest, count = hashlib.sha256(), 0
    try:
        with requests.get(url, headers={"Authorization": "Bearer " + token} if token else {},
                          stream=True, timeout=(30, 120)) as response:
            if response.status_code != 200:
                raise RuntimeError("Official checkpoint HTTP status " + str(response.status_code))
            for chunk in response.iter_content(1 << 20):
                if chunk:
                    stream.write(chunk)
                    digest.update(chunk)
                    count += len(chunk)
        stream.flush()
    finally:
        if not args.stdout:
            stream.close()
    if count != SIZE or digest.hexdigest() != SHA:
        raise ValueError("Downloaded checkpoint failed size/SHA256 verification")
    print(json.dumps(dict(source="facebook/sam3", revision=REV, bytes=count, sha256=SHA)), file=sys.stderr)


if __name__ == "__main__":
    main()
