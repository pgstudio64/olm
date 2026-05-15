"""One-shot migration: rename standard keys in JSON data files.

Replaces AFNOR_ADVICE -> standard1, GROUP -> standard2, SITE -> standard3
in values and dict keys of patterns.json, plans/*.json, and test fixtures.

Usage:
    python scripts/migrate_standard_keys.py [--dry-run]
"""
import argparse
import json
import logging
import shutil
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

MAPPING = {
    "AFNOR_ADVICE": "standard1",
    "GROUP": "standard2",
    "SITE": "standard3",
}

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _migrate_value(obj):
    """Recursively replace old standard names in JSON values and dict keys."""
    if isinstance(obj, str):
        return MAPPING.get(obj, obj)
    if isinstance(obj, list):
        return [_migrate_value(v) for v in obj]
    if isinstance(obj, dict):
        new = {}
        for k, v in obj.items():
            new_key = MAPPING.get(k, k)
            new[new_key] = _migrate_value(v)
        return new
    return obj


def migrate_file(path: Path, dry_run: bool) -> bool:
    """Migrate a single JSON file. Returns True if modified."""
    with open(path, encoding="utf-8") as f:
        original = f.read()
    try:
        data = json.loads(original)
    except json.JSONDecodeError:
        logger.warning("  SKIP (invalid JSON): %s", path)
        return False

    migrated = _migrate_value(data)
    new_text = json.dumps(migrated, indent=2, ensure_ascii=False) + "\n"

    if new_text == original:
        return False

    if dry_run:
        logger.info("  WOULD modify: %s", path.relative_to(PROJECT_ROOT))
    else:
        shutil.copy2(str(path), str(path) + ".bak")
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_text)
        logger.info("  Modified: %s", path.relative_to(PROJECT_ROOT))
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Migrate standard keys in JSON files")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would change without writing")
    args = parser.parse_args()

    targets: list[Path] = []

    # Catalogue
    cat = PROJECT_ROOT / "project" / "catalogue" / "patterns.json"
    if cat.exists():
        targets.append(cat)

    # Plans (recursive)
    plans_dir = PROJECT_ROOT / "project" / "plans"
    if plans_dir.is_dir():
        targets.extend(sorted(plans_dir.rglob("*.json")))

    # Test fixtures
    tests_dir = PROJECT_ROOT / "olm" / "tests"
    if tests_dir.is_dir():
        targets.extend(sorted(tests_dir.rglob("*.json")))

    modified = 0
    unchanged = 0
    for path in targets:
        if migrate_file(path, args.dry_run):
            modified += 1
        else:
            unchanged += 1

    label = "Would modify" if args.dry_run else "Modified"
    logger.info("\n%s: %d files, Unchanged: %d files", label, modified,
                unchanged)


if __name__ == "__main__":
    main()
