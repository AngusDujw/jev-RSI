"""Create a project uv overlay without modifying a shared simulator environment.

Reuse installed binary runtime packages read-only; install every differing
official direct/constraint pin into the project overlay from audited wheels.
The external site's editable .pth files are deliberately not executed.
"""
import argparse
import json
from pathlib import Path
import re
import subprocess
import zipfile
from email.parser import Parser


def output(command):
    return subprocess.check_output(command, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-python", required=True)
    parser.add_argument("--wheels", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    pins = {}
    for path in (root/"setup/requirements-sim.txt", root/"setup/constraints-sim.txt"):
        for line in path.read_text().splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                match = re.fullmatch(r"([\w.-]+)==([\w.+-]+)", line)
                if not match:
                    raise ValueError(f"Unsupported pin: {line}")
                pins[match[1]] = match[2]
    script = "import json,sysconfig; from importlib.metadata import version,PackageNotFoundError; names=" + repr(list(pins)) + "; versions={}\nfor n in names:\n try: versions[n]=version(n)\n except PackageNotFoundError: versions[n]=None\nprint(json.dumps(dict(site=sysconfig.get_paths()[\"purelib\"],versions=versions)))"
    base = json.loads(output([args.base_python, "-c", script]))
    overlays = [f"{name}=={version}" for name, version in pins.items()
                if (base["versions"][name] or "").split("+")[0] != version]
    # A changed package may require an exact binary companion even when that
    # companion is not itself a top-level harness pin (e.g. pydantic-core).
    for spec in list(overlays):
        name, version = spec.split("==")
        matches = list(args.wheels.glob(name.replace("-", "_") + "-" + version + "-*.whl"))
        for wheel in matches[:1]:
            with zipfile.ZipFile(wheel) as archive:
                metadata = next(n for n in archive.namelist() if n.endswith(".dist-info/METADATA"))
                fields = Parser().parsestr(archive.read(metadata).decode())
                for requirement in fields.get_all("Requires-Dist", []):
                    exact = re.fullmatch(r"([\w.-]+)\s*==\s*([\w.+-]+)", requirement)
                    if exact and exact[0] not in overlays:
                        overlays.append(exact[1]+"=="+exact[2])
    target = root/".venv-sim"
    if not target.exists():
        subprocess.run(["uv", "venv", "--python", args.base_python, str(target)], check=True)
    python = target/"bin/python"
    site = Path(output([str(python), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"]))
    shared_site = Path(base["site"])
    fallback = [str(shared_site)]
    cmeel = shared_site/"cmeel.prefix/lib/python3.11/site-packages"
    if cmeel.is_dir():
        fallback.append(str(cmeel))
    if (shared_site/"_cuda_bindings_redirector.py").exists():
        fallback.append("import _cuda_bindings_redirector")
    (site/"roboicl_readonly_runtime.pth").write_text("\n".join(fallback)+"\n")
    if overlays:
        subprocess.run(["uv", "pip", "install", "--python", str(python), "--offline", "--no-index", "--no-deps",
                        "--find-links", str(args.wheels.resolve()), *overlays], check=True)
    final = json.loads(output([str(python), "-c", script]))
    mismatches = {name: final["versions"][name] for name, version in pins.items()
                  if (final["versions"][name] or "").split("+")[0] != version}
    if mismatches:
        raise ValueError(f"Overlay pins remain different: {mismatches}")
    report = dict(base_python=args.base_python, overlay_python=str(python), base=base,
                  installed_overlays=overlays, final=final, shared_environment_modified=False)
    (root/".runtime/sim-overlay.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
