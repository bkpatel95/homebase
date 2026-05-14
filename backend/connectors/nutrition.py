"""Nutrition connector — markdown recipes parsed from a mounted directory."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from .base import ConfigField, Connector

CATEGORIES = ["breakfast", "lunch", "dinner"]

_MACRO_RE = re.compile(
    r"\|\s*Protein\s*\|\s*Carbs\s*\|\s*Fat\s*\|\s*Calories\s*\|"
    r".*?\|\s*([0-9.]+\s*\w*)\s*\|\s*([0-9.]+\s*\w*)\s*\|\s*([0-9.]+\s*\w*)\s*\|\s*([^|]+?)\s*\|",
    re.DOTALL | re.IGNORECASE,
)


def _pick_for_today(category: str, files: list[Path]) -> Path | None:
    if not files:
        return None
    if len(files) == 1:
        return files[0]
    seed = f"{category}-{date.today().isoformat()}".encode()
    idx = int(hashlib.sha256(seed).hexdigest(), 16) % len(files)
    return files[idx]


def _parse_recipe(path: Path) -> dict[str, Any]:
    text = path.read_text(errors="replace")
    title = path.stem.replace("-", " ").title()
    m = re.search(r"^#\s+(.+?)\s*$", text, re.MULTILINE)
    if m:
        title = m.group(1).strip()

    components: list[str] = []
    daily = re.search(r"##\s*Daily Meal\s*(.+?)(?:\n##|\Z)", text, re.DOTALL)
    if daily:
        for line in daily.group(1).splitlines():
            line = line.strip()
            if line.startswith(("-", "*")):
                components.append(line.lstrip("-* ").strip())

    macros = None
    mm = _MACRO_RE.search(text)
    if mm:
        macros = {
            "protein": mm.group(1).strip(),
            "carbs": mm.group(2).strip(),
            "fat": mm.group(3).strip(),
            "calories": mm.group(4).strip(),
        }

    return {
        "file": path.name,
        "title": title,
        "components": components[:5],
        "macros": macros,
    }


class NutritionConnector(Connector):
    id = "nutrition"
    name = "Recipe Library"
    description = "Picks today's breakfast, lunch, and dinner from a markdown recipe folder."
    icon = "🍴"
    category = "personal"
    widget_ids = ("nutrition",)
    config_schema = (
        ConfigField(
            name="recipe_dir",
            label="Recipe directory",
            type="path",
            required=True,
            help="Container path with breakfast/, lunch/, dinner/ subdirectories of *.md files.",
            placeholder="/data/recipes",
            default="/data/recipes",
            env_fallback="RECIPE_DIR",
        ),
    )

    async def test_connection(self, config: dict[str, Any]) -> dict[str, Any]:
        d = Path(config.get("recipe_dir") or "")
        if not d.exists():
            return {"ok": False, "detail": f"directory does not exist: {d}"}
        found = sum(1 for c in CATEGORIES if (d / c).is_dir() and any((d / c).glob("*.md")))
        if not found:
            return {"ok": False, "detail": f"no recipe subdirs found in {d}"}
        return {"ok": True, "detail": f"{found}/{len(CATEGORIES)} meal categories populated"}

    async def collect(self, config: dict[str, Any]) -> dict[str, Any]:
        recipe_dir = Path(config.get("recipe_dir") or "")
        now = datetime.now(UTC).isoformat()
        if not recipe_dir.exists():
            return {
                "nutrition": {
                    "available": False,
                    "reason": f"No recipe directory at {recipe_dir}.",
                    "meals": [],
                    "collected_at": now,
                }
            }

        meals: list[dict[str, Any]] = []
        for cat in CATEGORIES:
            files = sorted((recipe_dir / cat).glob("*.md")) if (recipe_dir / cat).is_dir() else []
            chosen = _pick_for_today(cat, files)
            if not chosen:
                continue
            recipe = _parse_recipe(chosen)
            meals.append({"category": cat, **recipe})

        total_cal = 0
        for m in meals:
            cal = (m.get("macros") or {}).get("calories", "")
            digits = re.search(r"(\d{2,5})", cal)
            if digits:
                total_cal += int(digits.group(1))

        return {
            "nutrition": {
                "available": bool(meals),
                "meals": meals,
                "total_calories_est": total_cal or None,
                "collected_at": now,
            }
        }


connector = NutritionConnector()
