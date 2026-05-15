"""Tests for scripts/generate_plan_variants.py (D-205)."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile

import pytest

from scripts.generate_plan_variants import (
    DEFAULT_VARIANT_NAMES,
    SOURCE_PREFIX,
    generate_variants,
    _compute_median_door_width_cm,
    _measure_wall_thickness,
    _parse_scale_measured,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SOURCE_BASENAME = "big_pillars"
PLANS_DIR = os.path.join(
    os.path.dirname(__file__), os.pardir, os.pardir,
    "project", "plans",
)

_SOURCE_JSON = os.path.join(
    PLANS_DIR, f"{SOURCE_PREFIX}{SOURCE_BASENAME}.json",
)
_SOURCE_PNG = os.path.join(
    PLANS_DIR, f"{SOURCE_PREFIX}{SOURCE_BASENAME}-SD.png",
)

def _check_source_available() -> bool:
    """Check source files exist AND have required fields."""
    if not os.path.exists(_SOURCE_JSON) or not os.path.exists(_SOURCE_PNG):
        return False
    try:
        with open(_SOURCE_JSON) as f:
            data = json.load(f)
        if "drawing_scale_measured" not in data:
            return False
        rooms = data.get("rooms", {})
        return any("bbox_px" in r for r in rooms.values())
    except (json.JSONDecodeError, OSError):
        return False


_source_available = _check_source_available()
skip_no_source = pytest.mark.skipif(
    not _source_available,
    reason="big_pillars source files not available or incomplete",
)


@pytest.fixture(scope="module")
def workdir():
    """Create a temp dir with copies of source files, run generation once."""
    if not _source_available:
        pytest.skip("big_pillars source files not available")

    tmpdir = tempfile.mkdtemp(prefix="olm_variants_")
    # Copy source files
    shutil.copy2(_SOURCE_JSON, tmpdir)
    shutil.copy2(_SOURCE_PNG, tmpdir)

    generate_variants(SOURCE_BASENAME, tmpdir)
    yield tmpdir

    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest.fixture(scope="module")
def source_json():
    """Load source JSON."""
    if not _source_available:
        pytest.skip("big_pillars source files not available")
    with open(_SOURCE_JSON) as f:
        return json.load(f)


@pytest.fixture(scope="module")
def variant_jsons(workdir):
    """Load all 3 variant JSONs."""
    result = {}
    for name in DEFAULT_VARIANT_NAMES:
        path = os.path.join(workdir, f"{name}.json")
        with open(path) as f:
            result[name] = json.load(f)
    return result


@pytest.fixture(scope="module")
def source_scale(source_json):
    """Source scale in cm/px."""
    return _parse_scale_measured(source_json["drawing_scale_measured"])


@pytest.fixture(scope="module")
def factor_v1(source_json, source_scale):
    """Computed factor_v1."""
    median = _compute_median_door_width_cm(source_json["rooms"], source_scale)
    return 90.0 / median


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@skip_no_source
class TestVariantDoors:
    """Door width and offset tests."""

    def test_v1_doors_90_cm(self, variant_jsons):
        """All V1 doors have width_cm = 90 (via width_px * scale)."""
        v1 = variant_jsons["test_office_1"]
        scale = _parse_scale_measured(v1["drawing_scale_measured"])
        for rid, room in v1["rooms"].items():
            for door in room.get("doors", []):
                w_cm = door["width_px"] * scale
                assert abs(w_cm - 90.0) < 1.0, (
                    f"Room {rid}: width_cm={w_cm:.1f}, expected ~90"
                )

    def test_v2_door_widths_preserved(self, variant_jsons):
        """All V2 doors have width_cm = 90."""
        v2 = variant_jsons["test_office_2"]
        scale = _parse_scale_measured(v2["drawing_scale_measured"])
        for rid, room in v2["rooms"].items():
            for door in room.get("doors", []):
                w_cm = door["width_px"] * scale
                assert abs(w_cm - 90.0) < 1.0, (
                    f"Room {rid}: width_cm={w_cm:.1f}, expected ~90"
                )

    def test_v3_door_widths_preserved(self, variant_jsons):
        """All V3 doors have width_cm = 90."""
        v3 = variant_jsons["test_office_3"]
        scale = _parse_scale_measured(v3["drawing_scale_measured"])
        for rid, room in v3["rooms"].items():
            for door in room.get("doors", []):
                w_cm = door["width_px"] * scale
                assert abs(w_cm - 90.0) < 1.5, (
                    f"Room {rid}: width_cm={w_cm:.1f}, expected ~90"
                )

    def test_v2_door_offsets_absolute(self, variant_jsons):
        """Door offset_cm in V2 = offset_cm in V1 (tolerance 1 cm)."""
        v1 = variant_jsons["test_office_1"]
        v2 = variant_jsons["test_office_2"]
        scale_v1 = _parse_scale_measured(v1["drawing_scale_measured"])
        scale_v2 = _parse_scale_measured(v2["drawing_scale_measured"])
        for rid in v1["rooms"]:
            doors_v1 = v1["rooms"][rid].get("doors", [])
            doors_v2 = v2["rooms"][rid].get("doors", [])
            assert len(doors_v1) == len(doors_v2), (
                f"Room {rid}: door count mismatch"
            )
            for i, (d1, d2) in enumerate(zip(doors_v1, doors_v2)):
                off_cm_v1 = d1["offset_px"] * scale_v1
                off_cm_v2 = d2["offset_px"] * scale_v2
                assert abs(off_cm_v1 - off_cm_v2) < 1.0, (
                    f"Room {rid} door {i}: "
                    f"offset_cm V1={off_cm_v1:.1f} V2={off_cm_v2:.1f}"
                )


@skip_no_source
class TestSurfaceHomothety:
    """Surface must be source × cumulative_factor²."""

    def test_surface_homothety_v1(self, variant_jsons, source_json, factor_v1):
        """V1 surface = source surface × factor_v1²."""
        v1 = variant_jsons["test_office_1"]
        for rid in source_json["rooms"]:
            src_s = float(source_json["rooms"][rid]["surface"].split()[0])
            v1_s = float(v1["rooms"][rid]["surface"].split()[0])
            expected = src_s * factor_v1 ** 2
            assert abs(v1_s - expected) < 0.1, (
                f"Room {rid}: V1 surface {v1_s} != expected {expected:.2f}"
            )

    def test_surface_homothety_v2(self, variant_jsons, source_json, factor_v1):
        """V2 surface = source surface × (factor_v1 * 1.2)²."""
        v2 = variant_jsons["test_office_2"]
        factor = factor_v1 * 1.2
        for rid in source_json["rooms"]:
            src_s = float(source_json["rooms"][rid]["surface"].split()[0])
            v2_s = float(v2["rooms"][rid]["surface"].split()[0])
            expected = src_s * factor ** 2
            assert abs(v2_s - expected) < 0.1, (
                f"Room {rid}: V2 surface {v2_s} != expected {expected:.2f}"
            )

    def test_surface_homothety_v3(self, variant_jsons, source_json, factor_v1):
        """V3 surface = source surface × (factor_v1 * 1.44)²."""
        v3 = variant_jsons["test_office_3"]
        factor = factor_v1 * 1.44
        for rid in source_json["rooms"]:
            src_s = float(source_json["rooms"][rid]["surface"].split()[0])
            v3_s = float(v3["rooms"][rid]["surface"].split()[0])
            expected = src_s * factor ** 2
            assert abs(v3_s - expected) < 0.1, (
                f"Room {rid}: V3 surface {v3_s} != expected {expected:.2f}"
            )


@skip_no_source
class TestScalingFactors:
    """Scale factor tests."""

    def test_v2_scaling_factor(self, variant_jsons, source_json, factor_v1):
        """V2 cumulative factor ≈ factor_v1 * 1.2."""
        source_scale = _parse_scale_measured(
            source_json["drawing_scale_measured"],
        )
        v2_scale = _parse_scale_measured(
            variant_jsons["test_office_2"]["drawing_scale_measured"],
        )
        actual_factor = v2_scale / source_scale
        expected = factor_v1 * 1.2
        assert abs(actual_factor - expected) < 0.01, (
            f"V2 factor {actual_factor:.4f} != expected {expected:.4f}"
        )

    def test_v3_cumulative_factor(self, variant_jsons, source_json, factor_v1):
        """V3 cumulative factor ≈ factor_v1 * 1.44."""
        source_scale = _parse_scale_measured(
            source_json["drawing_scale_measured"],
        )
        v3_scale = _parse_scale_measured(
            variant_jsons["test_office_3"]["drawing_scale_measured"],
        )
        actual_factor = v3_scale / source_scale
        expected = factor_v1 * 1.44
        assert abs(actual_factor - expected) < 0.01, (
            f"V3 factor {actual_factor:.4f} != expected {expected:.4f}"
        )


@skip_no_source
class TestWindowsAndImages:
    """Window scaling and image dimension tests."""

    def test_windows_widths_scaled(self, variant_jsons):
        """Window width_cm in V2 / V1 ≈ 1.2 (homothétie)."""
        v1 = variant_jsons["test_office_1"]
        v2 = variant_jsons["test_office_2"]
        scale_v1 = _parse_scale_measured(v1["drawing_scale_measured"])
        scale_v2 = _parse_scale_measured(v2["drawing_scale_measured"])
        ratios = []
        for rid in v1["rooms"]:
            wins_v1 = v1["rooms"][rid].get("windows", [])
            wins_v2 = v2["rooms"][rid].get("windows", [])
            for w1, w2 in zip(wins_v1, wins_v2):
                cm_v1 = w1["width_px"] * scale_v1
                cm_v2 = w2["width_px"] * scale_v2
                if cm_v1 > 0:
                    ratios.append(cm_v2 / cm_v1)
        assert ratios, "No windows found"
        avg_ratio = sum(ratios) / len(ratios)
        assert abs(avg_ratio - 1.2) < 0.01, (
            f"Window width ratio V2/V1 = {avg_ratio:.3f}, expected ~1.2"
        )

    def test_image_pixel_count_preserved(self, workdir, source_json):
        """All 3 PNGs have the same pixel dimensions as source."""
        from PIL import Image
        expected_w = source_json["page_width_px"]
        expected_h = source_json["page_height_px"]
        for name in DEFAULT_VARIANT_NAMES:
            path = os.path.join(workdir, f"{name}-SD.png")
            img = Image.open(path)
            assert img.size == (expected_w, expected_h), (
                f"{name}: {img.size} != ({expected_w}, {expected_h})"
            )


@skip_no_source
class TestDoorSeeds:
    """Door seed generation tests."""

    def test_door_seeds_inside_bbox(self, variant_jsons):
        """Each generated seed_x, seed_y is inside the room bbox."""
        for vname, vdata in variant_jsons.items():
            for rid, room in vdata["rooms"].items():
                bbox = room.get("bbox_px")
                if not bbox:
                    continue
                for seed in room.get("door_seeds", []):
                    sx, sy = seed["seed_x"], seed["seed_y"]
                    assert bbox[0] <= sx <= bbox[2], (
                        f"{vname}/{rid}: seed_x={sx} outside bbox x"
                    )
                    assert bbox[1] <= sy <= bbox[3], (
                        f"{vname}/{rid}: seed_y={sy} outside bbox y"
                    )

    def test_door_seeds_count_matches_typed(self, variant_jsons):
        """Number of door_seeds = number of typed doors per room."""
        for vname, vdata in variant_jsons.items():
            for rid, room in vdata["rooms"].items():
                n_doors = len(room.get("doors", []))
                n_seeds = len(room.get("door_seeds", []))
                if n_doors == 0:
                    assert "door_seeds" not in room or n_seeds == 0, (
                        f"{vname}/{rid}: has door_seeds but no doors"
                    )
                else:
                    assert n_seeds == n_doors, (
                        f"{vname}/{rid}: {n_seeds} seeds != {n_doors} doors"
                    )


@skip_no_source
class TestIdempotent:
    """Idempotency test."""

    def test_idempotent(self):
        """Two consecutive runs produce identical files (SHA-256)."""
        tmpdir1 = tempfile.mkdtemp(prefix="olm_idem1_")
        tmpdir2 = tempfile.mkdtemp(prefix="olm_idem2_")
        try:
            for d in (tmpdir1, tmpdir2):
                shutil.copy2(_SOURCE_JSON, d)
                shutil.copy2(_SOURCE_PNG, d)

            generate_variants(SOURCE_BASENAME, tmpdir1)
            generate_variants(SOURCE_BASENAME, tmpdir2)

            for name in DEFAULT_VARIANT_NAMES:
                for ext in (".json", "-SD.png"):
                    fname = f"{name}{ext}"
                    h1 = _sha256(os.path.join(tmpdir1, fname))
                    h2 = _sha256(os.path.join(tmpdir2, fname))
                    assert h1 == h2, f"{fname}: SHA-256 mismatch"
        finally:
            shutil.rmtree(tmpdir1, ignore_errors=True)
            shutil.rmtree(tmpdir2, ignore_errors=True)


@skip_no_source
class TestWallThickness:
    """Wall auto-measurement and consistency tests."""

    def test_walls_thickness_consistent(self, workdir, source_json):
        """Wall thickness in a variant matches the auto-measured source."""
        from PIL import Image as PILImage

        source_png = os.path.join(
            PLANS_DIR, f"{SOURCE_PREFIX}{SOURCE_BASENAME}-SD.png",
        )
        source_img = PILImage.open(source_png).convert("RGB")
        source_thickness = _measure_wall_thickness(
            source_img, source_json["rooms"],
        )

        variant_png = os.path.join(workdir, "test_office_1-SD.png")
        variant_img = PILImage.open(variant_png).convert("RGB")

        with open(os.path.join(workdir, "test_office_1.json")) as f:
            v1 = json.load(f)
        variant_thickness = _measure_wall_thickness(
            variant_img, v1["rooms"],
        )

        assert abs(variant_thickness - source_thickness) <= 3, (
            f"Variant wall={variant_thickness}, "
            f"source wall={source_thickness}, "
            f"tolerance is 3 px"
        )


@skip_no_source
class TestArcDrawn:
    """Door arc presence tests."""

    def test_arc_drawn_at_door(self, workdir, variant_jsons):
        """Black pixels exist in the arc region around each typed door."""
        from PIL import Image as PILImage
        import numpy as np

        v1 = variant_jsons["test_office_1"]
        variant_png = os.path.join(workdir, "test_office_1-SD.png")
        img = PILImage.open(variant_png).convert("RGB")
        arr = np.array(img)

        for rid, room in v1["rooms"].items():
            bbox = room.get("bbox_px")
            if not bbox:
                continue
            bx1, by1, bx2, by2 = bbox

            for door in room.get("doors", []):
                face = door["face"]
                off = door["offset_px"]
                w = door["width_px"]
                r = w  # Arc radius.

                # Define a bounding box for where the arc should be.
                if face == "south":
                    ax1 = bx1 + off
                    ax2 = ax1 + w
                    ay1 = by2 - r
                    ay2 = by2 + r
                elif face == "north":
                    ax1 = bx1 + off
                    ax2 = ax1 + w
                    ay1 = by1 - r
                    ay2 = by1 + r
                elif face == "east":
                    ax1 = bx2 - r
                    ax2 = bx2 + r
                    ay1 = by1 + off
                    ay2 = ay1 + w
                elif face == "west":
                    ax1 = bx1 - r
                    ax2 = bx1 + r
                    ay1 = by1 + off
                    ay2 = ay1 + w
                else:
                    continue

                # Clamp to image bounds.
                ax1 = max(0, ax1)
                ay1 = max(0, ay1)
                ax2 = min(arr.shape[1], ax2)
                ay2 = min(arr.shape[0], ay2)

                region = arr[ay1:ay2, ax1:ax2]
                black_count = int(
                    np.all(region < 50, axis=2).sum()
                )
                assert black_count > 5, (
                    f"Room {rid} door {face}: only {black_count} "
                    f"black pixels in arc region"
                )


@skip_no_source
class TestPixelQuality:
    """PNG pixel quality tests (no excessive grey pollution)."""

    def test_no_excessive_grey_pollution(self, workdir, source_json):
        """Source black pixels that became grey in V1 are < 5%."""
        from PIL import Image as PILImage
        import numpy as np

        source_png = os.path.join(
            PLANS_DIR, f"{SOURCE_PREFIX}{SOURCE_BASENAME}-SD.png",
        )
        source_arr = np.array(
            PILImage.open(source_png).convert("RGB"),
        )
        variant_arr = np.array(
            PILImage.open(
                os.path.join(workdir, "test_office_1-SD.png"),
            ).convert("RGB"),
        )

        # Black pixels in source (all channels < 50).
        source_black = np.all(source_arr < 50, axis=2)
        total_black = int(source_black.sum())

        # Among source black pixels, how many became grey in variant?
        # Grey = not black (any channel >= 50) and not white
        # (any channel < 200).
        variant_at_black = variant_arr[source_black]
        not_black = np.any(variant_at_black >= 50, axis=1)
        not_white = np.any(variant_at_black < 200, axis=1)
        became_grey = int((not_black & not_white).sum())

        pct = became_grey / total_black * 100 if total_black > 0 else 0
        assert pct < 5.0, (
            f"{became_grey} source black pixels became grey "
            f"({pct:.1f}% of {total_black}), limit is 5%"
        )


@skip_no_source
class TestReanalyzeBatch:
    """Bonus: variant is consumable by OLM reanalyze_batch."""

    def test_reanalyze_batch_on_variant(self, workdir, variant_jsons):
        """Load test_office_2 via reanalyze_batch — no errors expected."""
        try:
            from olm.server.services.ingestion_service import reanalyze_batch
        except ImportError:
            pytest.skip("olm.server not available")

        v2 = variant_jsons["test_office_2"]
        png_path = os.path.join(workdir, "test_office_2-SD.png")
        if not os.path.exists(png_path):
            pytest.skip("test_office_2-SD.png not found")

        scale = _parse_scale_measured(v2["drawing_scale_measured"])

        rooms_payload = []
        for rid, room in v2.get("rooms", {}).items():
            bbox = room.get("bbox_px")
            if not bbox or len(bbox) != 4:
                continue
            entry: dict = {
                "name": rid,
                "bbox_px": bbox,
                "seed_px": [room["seed_x"], room["seed_y"]],
                "doors": room.get("doors", []),
            }
            if room.get("door_seeds"):
                entry["door_seeds"] = room["door_seeds"]
            rooms_payload.append(entry)

        data = {
            "plan_path": png_path,
            "scale_cm_per_px": scale,
            "rooms": rooms_payload,
            "mode": "preprocessed",
        }

        result = reanalyze_batch(data)
        assert "results" in result

        errors = [r for r in result["results"] if r.get("error")]
        assert len(errors) == 0, (
            f"{len(errors)} rooms errored: "
            + ", ".join(f"{e['name']}: {e['error']}" for e in errors)
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sha256(path: str) -> str:
    """Compute SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()
