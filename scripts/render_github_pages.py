#!/usr/bin/env python3
"""Render and verify the two-architecture ZXTouch Sileo repository."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import lzma
import re
import shutil
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "https://gitssie.github.io/zxtouchrootless"
REPOSITORY_URL = "https://github.com/gitssie/zxtouchrootless"
PACKAGE_ID = "com.zjx.ioscontrol"


def fail(message: str) -> None:
    raise ValueError(message)


def deb_member(path: Path, name: str) -> bytes:
    data = path.read_bytes()
    if not data.startswith(b"!<arch>\n"):
        fail(f"{path}: invalid deb archive")
    offset = 8
    while offset + 60 <= len(data):
        header = data[offset : offset + 60]
        if header[58:60] != b"`\n":
            fail(f"{path}: invalid ar member")
        member_name = header[:16].decode("ascii").strip().rstrip("/")
        size = int(header[48:58].decode("ascii").strip())
        start = offset + 60
        end = start + size
        if end > len(data):
            fail(f"{path}: truncated ar member")
        if member_name == name:
            return data[start:end]
        offset = end + (size % 2)
    fail(f"{path}: missing {name}")


def deb_control(path: Path) -> tuple[dict[str, str], str]:
    control_archive = deb_member(path, "control.tar.gz")
    with tarfile.open(fileobj=io.BytesIO(control_archive), mode="r:gz") as archive:
        control_file = archive.extractfile("./control")
        postinst_file = archive.extractfile("./postinst")
        if control_file is None or postinst_file is None:
            fail(f"{path}: missing control or postinst")
        control_text = control_file.read().decode("utf-8")
        postinst = postinst_file.read().decode("utf-8")
    fields: dict[str, str] = {}
    for line in control_text.splitlines():
        if line.startswith((" ", "\t")):
            continue
        if ":" not in line:
            fail(f"{path}: malformed control line")
        key, value = line.split(":", 1)
        if key in fields:
            fail(f"{path}: duplicate control field {key}")
        fields[key] = value.strip()
    return fields, postinst


def digest(data: bytes, algorithm: str) -> str:
    return hashlib.new(algorithm, data).hexdigest()


def package_entry(path: Path, architecture: str, flavor: str, version: str) -> tuple[str, bytes]:
    if not path.is_file() or path.is_symlink():
        fail(f"missing package: {path}")
    fields, postinst = deb_control(path)
    if fields.get("Package") != PACKAGE_ID:
        fail(f"{path}: package identifier does not match")
    if fields.get("Version") != version or fields.get("Architecture") != architecture:
        fail(f"{path}: version or architecture does not match source")
    if flavor == "roothide" and "jbroot" not in postinst:
        fail(f"{path}: roothide postinst is missing jbroot")
    if flavor == "rootless" and "/var/jb" not in postinst:
        fail(f"{path}: rootless postinst is missing /var/jb")
    payload = path.read_bytes()
    filename = f"debs/{PACKAGE_ID}_{version}_{flavor}.deb"
    apt_fields = {
        **fields,
        "Name": "ZXTouch (Roothide)" if flavor == "roothide" else "ZXTouch",
        "Filename": filename,
        "Size": str(len(payload)),
        "MD5sum": digest(payload, "md5"),
        "SHA1": digest(payload, "sha1"),
        "SHA256": digest(payload, "sha256"),
        "Homepage": BASE_URL,
        "Depiction": BASE_URL,
        "SileoDepiction": BASE_URL + "/depiction.json",
    }
    stanza = "\n".join(f"{key}: {value}" for key, value in apt_fields.items())
    return stanza, payload


def render(rootless: Path, roothide: Path, output: Path) -> dict[str, str]:
    version_line = next(
        (line for line in (ROOT / "control").read_text().splitlines() if line.startswith("Version: ")),
        None,
    )
    if version_line is None:
        fail("source control has no Version")
    version = version_line.split(":", 1)[1].strip()
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)+", version):
        fail("source version is not a dotted numeric version")
    if output.exists() and any(output.iterdir()):
        fail("output directory must be empty")
    output.mkdir(parents=True, exist_ok=True)
    (output / "debs").mkdir()

    entries = []
    for package, architecture, flavor in (
        (roothide, "iphoneos-arm64e", "roothide"),
        (rootless, "iphoneos-arm64", "rootless"),
    ):
        stanza, payload = package_entry(package, architecture, flavor, version)
        entries.append(stanza)
        (output / "debs" / f"{PACKAGE_ID}_{version}_{flavor}.deb").write_bytes(payload)

    packages = ("\n\n".join(entries) + "\n").encode()
    indexes = {
        "Packages": packages,
        "Packages.gz": gzip.compress(packages, mtime=0),
        "Packages.xz": lzma.compress(packages, format=lzma.FORMAT_XZ),
    }
    zstd = subprocess.run(("zstd", "-q", "-c"), input=packages, capture_output=True, check=True)
    indexes["Packages.zst"] = zstd.stdout
    for name, payload in indexes.items():
        (output / name).write_bytes(payload)

    release_lines = [
        "Origin: ZXTouch Rootless",
        "Label: ZXTouch Rootless",
        "Suite: stable",
        "Version: 1.0",
        "Codename: ios",
        "Architectures: iphoneos-arm64 iphoneos-arm64e",
        "Components: main",
        "Description: ZXTouch Rootless packages for iOS 15-17",
    ]
    for section, algorithm in (("MD5Sum", "md5"), ("SHA1", "sha1"), ("SHA256", "sha256")):
        release_lines.append(section + ":")
        for name, payload in indexes.items():
            release_lines.append(f" {digest(payload, algorithm)} {len(payload)} {name}")
    (output / "Release").write_text("\n".join(release_lines) + "\n")

    index = (ROOT / "pages/index.html").read_text()
    index = index.replace("https://epic0001.github.io/zxtouchrootless/", BASE_URL)
    index = index.replace("https://github.com/Epic0001/zxtouchrootless", REPOSITORY_URL)
    index = index.replace("zxtouch_*_rootless.deb", f"{PACKAGE_ID}_{version}_rootless.deb")
    index = index.replace("zxtouch_*_roothide.deb", f"{PACKAGE_ID}_{version}_roothide.deb")
    index = index.replace("{{VERSION}}", version)
    if "epic0001.github.io/zxtouchrootless" in index:
        fail("site template still contains the old source URL")
    if re.search(r"\{\{[A-Z0-9_]+\}\}", index):
        fail("site template contains an unresolved placeholder")
    (output / "index.html").write_text(index)

    depiction = json.loads((ROOT / "pages/depiction.json").read_text())
    depiction.pop("headerImage", None)
    depiction_text = json.dumps(depiction, ensure_ascii=False)
    depiction_text = depiction_text.replace("https://epic0001.github.io/zxtouchrootless", BASE_URL)
    depiction_text = depiction_text.replace("https://github.com/Epic0001/zxtouchrootless", REPOSITORY_URL)
    depiction = json.loads(depiction_text)
    changelog = depiction["tabs"][1]["views"][0]
    changelog["markdown"] = (
        f"## {version}\n- Fixed an OCR request retain cycle that could grow SpringBoard memory.\n"
        "- Updated the local Sileo package repository.\n\n" + changelog["markdown"]
    )
    (output / "depiction.json").write_text(json.dumps(depiction, indent=2, ensure_ascii=False) + "\n")
    shutil.copy2(ROOT / "pages/favicon.svg", output / "favicon.svg")
    (output / ".nojekyll").write_text("")

    verify(output, version)
    return {"version": version, "sha256_roothide": digest(roothide.read_bytes(), "sha256")}


def verify(output: Path, version: str) -> None:
    packages = (output / "Packages").read_bytes()
    if gzip.decompress((output / "Packages.gz").read_bytes()) != packages:
        fail("Packages.gz differs from Packages")
    if lzma.decompress((output / "Packages.xz").read_bytes()) != packages:
        fail("Packages.xz differs from Packages")
    decoded = subprocess.run(
        ("zstd", "-q", "-d", "-c", str(output / "Packages.zst")),
        capture_output=True,
        check=True,
    ).stdout
    if decoded != packages:
        fail("Packages.zst differs from Packages")
    stanzas = packages.decode().strip().split("\n\n")
    if len(stanzas) != 2:
        fail("Packages must have two entries")
    for stanza, flavor, architecture in zip(
        stanzas, ("roothide", "rootless"), ("iphoneos-arm64e", "iphoneos-arm64")
    ):
        fields = dict(line.split(": ", 1) for line in stanza.splitlines())
        package = output / fields["Filename"]
        payload = package.read_bytes()
        expected_filename = f"debs/{PACKAGE_ID}_{version}_{flavor}.deb"
        if fields["Filename"] != expected_filename or fields["Architecture"] != architecture:
            fail("Packages filename or architecture does not match")
        if fields["Size"] != str(len(payload)) or fields["SHA256"] != digest(payload, "sha256"):
            fail("Packages size or SHA256 does not match deb")
    release = (output / "Release").read_text()
    for name in ("Packages", "Packages.gz", "Packages.xz", "Packages.zst"):
        payload = (output / name).read_bytes()
        for algorithm in ("md5", "sha1", "sha256"):
            if f" {digest(payload, algorithm)} {len(payload)} {name}" not in release:
                fail(f"Release checksum missing for {name}")
    if BASE_URL not in (output / "index.html").read_text():
        fail("site does not contain the new Sileo source URL")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rootless", required=True, type=Path)
    parser.add_argument("--roothide", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        for key, value in render(args.rootless, args.roothide, args.output).items():
            print(f"{key}={value}")
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
