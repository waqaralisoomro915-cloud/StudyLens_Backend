"""Write installed runtime versions; run after resolving requirements.txt on Python 3.12."""

from importlib.metadata import distribution
from pathlib import Path
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

root = Path(__file__).resolve().parents[1]
pending = [
    Requirement(line)
    for line in (root / "requirements.txt").read_text().splitlines()
    if line.strip() and not line.startswith("#")
]
seen = set()
versions = {}
while pending:
    requirement = pending.pop()
    key = (canonicalize_name(requirement.name), tuple(sorted(requirement.extras)))
    if key in seen:
        continue
    seen.add(key)
    dist = distribution(requirement.name)
    versions[canonicalize_name(dist.metadata["Name"])] = dist.version
    for raw in dist.requires or []:
        child = Requirement(raw)
        if child.marker is None or any(child.marker.evaluate({"extra": extra}) for extra in ("", *requirement.extras)):
            pending.append(child)
(root / "requirements.lock").write_text(
    "# Resolved and tested runtime dependencies (Python 3.12).\n"
    + "\n".join(f"{name}=={version}" for name, version in sorted(versions.items()))
    + "\n"
)
print(f"Locked {len(versions)} runtime packages")
