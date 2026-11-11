"""Use a signed Ubuntu archive mirror when the hosted runner's mirrors fail."""
from __future__ import annotations

import os
from pathlib import Path
import re
import stat
import tempfile


SOURCE = Path("/etc/apt/sources.list.d/ubuntu.sources")
MIRROR = "https://mirrors.edge.kernel.org/ubuntu/"
KEYRING = "/usr/share/keyrings/ubuntu-archive-keyring.gpg"
KNOWN_URIS = {
    "mirror+file:/etc/apt/apt-mirrors.txt",
    MIRROR.rstrip("/"),
    *(f"{scheme}://{host}/ubuntu" for scheme in ("http", "https")
      for host in ("azure.archive.ubuntu.com", "archive.ubuntu.com", "security.ubuntu.com")),
}
KNOWN_SUITES = {"noble", "noble-updates", "noble-backports", "noble-security"}
KNOWN_COMPONENTS = {"main", "restricted", "universe", "multiverse"}
KNOWN_FIELDS = {"types", "uris", "suites", "components", "signed-by", "architectures"}


def fallback_sources(contents: str) -> str:
    """Validate the known Ubuntu 24.04 layout before changing only its URIs."""
    blocks = re.split(r"(\r?\n[ \t]*\r?\n)", contents)
    source_count = 0
    for index in range(0, len(blocks), 2):
        block = blocks[index]
        fields: dict[str, str] = {}
        for line in block.splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            match = re.fullmatch(r"([A-Za-z][A-Za-z-]*):[ \t]*(.*)", line)
            if match is None:
                raise ValueError("Unexpected multiline or malformed Ubuntu source field")
            name, value = match.group(1).lower(), match.group(2).strip()
            if name not in KNOWN_FIELDS or name in fields:
                raise ValueError("Unexpected or duplicate Ubuntu source field")
            fields[name] = value
        if not fields:
            continue
        if not {"types", "uris", "suites", "components", "signed-by"} <= fields.keys():
            raise ValueError("Ubuntu source is missing required fields")
        if fields["signed-by"] != KEYRING:
            raise ValueError("Ubuntu archive signature keyring must remain explicit")
        for field, allowed in (("types", {"deb", "deb-src"}),
                               ("suites", KNOWN_SUITES),
                               ("components", KNOWN_COMPONENTS)):
            values = fields[field].split()
            if not values or not set(values) <= allowed:
                raise ValueError(f"Unexpected Ubuntu source {field}")
        uris = fields["uris"].split()
        if len(uris) != 1 or uris[0].rstrip("/") not in KNOWN_URIS:
            raise ValueError("Unexpected Ubuntu archive URI")
        blocks[index] = re.sub(r"(?im)^([ \t]*URIs:[ \t]*)[^\r\n]*",
                               lambda match: match.group(1) + MIRROR, block)
        source_count += 1
    if not source_count:
        raise ValueError("No recognised Ubuntu sources found")
    return "".join(blocks)


def main() -> None:
    source_stat = SOURCE.lstat()
    if not stat.S_ISREG(source_stat.st_mode) or source_stat.st_size > 65536:
        raise ValueError("Expected a small regular Ubuntu source file")
    updated = fallback_sources(SOURCE.read_bytes().decode("utf-8"))
    temporary_name = None
    try:
        with tempfile.NamedTemporaryFile(dir=SOURCE.parent, prefix=".ubuntu.sources-", delete=False) as temporary:
            temporary_name = temporary.name
            os.fchmod(temporary.fileno(), stat.S_IMODE(source_stat.st_mode))
            temporary.write(updated.encode("utf-8"))
        os.replace(temporary_name, SOURCE)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
    print(f"Using {MIRROR} with the existing Ubuntu archive keyring and suites")


if __name__ == "__main__":
    main()
