"""Install the portable skills into a repository-scoped discovery directory."""
import argparse
from pathlib import Path
import shutil


def main():
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, help="Override the default workspace-root Codex and Claude directories")
    parser.add_argument("--update", action="store_true", help="Update existing copies of the named bundled skills")
    args = parser.parse_args()
    names = ("sabermapper-map", "sabermapper-research", "sabermapper-review", "sabermapper-vivify")
    destinations = [args.destination] if args.destination else [root.parent / ".agents" / "skills", root.parent / ".claude" / "skills"]
    pairs = [(root / "skills" / name, base / name) for base in destinations for name in names]
    for source, destination in pairs:
        if destination.exists() and not args.update:
            raise SystemExit(f"Already exists: {destination}. Pass --update to replace bundled files deliberately.")
        if destination.resolve() == source.resolve():
            raise SystemExit("Destination is the canonical skill source")
    for source, destination in pairs:
        shutil.copytree(source, destination, dirs_exist_ok=args.update)
        print(destination)


if __name__ == "__main__":
    main()
