from __future__ import annotations

import json
import re
from pathlib import Path

from .gates import GATE_TYPES

STEP_TYPES = {"command", "package"}
_VAR = re.compile(r"\$\{([A-Za-z0-9_]+)\}")


class RecipeError(ValueError):
    pass


def _require(cond: bool, message: str) -> None:
    if not cond:
        raise RecipeError(message)


def validate(recipe: dict, source: str = "<memory>") -> dict:
    _require(isinstance(recipe, dict), f"{source}: recipe must be an object")
    for key in ("id", "title", "device_families", "stages"):
        _require(key in recipe, f"{source}: missing key {key}")
    _require(bool(recipe["device_families"]), f"{source}: device_families is empty")
    _require(bool(recipe["stages"]), f"{source}: stages is empty")

    stage_ids = set()
    for stage in recipe["stages"]:
        for key in ("id", "title"):
            _require(key in stage, f"{source}: stage missing {key}")
        _require(stage["id"] not in stage_ids, f"{source}: duplicate stage {stage['id']}")
        stage_ids.add(stage["id"])
        _require(bool(stage.get("gates")), f"{source}: stage {stage['id']} has no gates")
        for step in stage.get("steps", []):
            _require(step.get("id") and step.get("type"), f"{source}: step needs id/type")
            _require(step["type"] in STEP_TYPES, f"{source}: unknown step type {step['type']}")
            if step["type"] == "command":
                _require(isinstance(step.get("command"), list) and step["command"],
                         f"{source}: command step needs non-empty list")
        for gate in stage.get("gates", []):
            _require(gate.get("id") and gate.get("type"), f"{source}: gate needs id/type")
            _require(gate["type"] in GATE_TYPES,
                     f"{source}: unknown gate type {gate['type']}")

    release_stage = recipe.get("release_stage")
    if release_stage is not None:
        _require(release_stage in stage_ids,
                 f"{source}: release_stage {release_stage!r} is not a stage")
    return recipe


def load_file(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        recipe = json.load(fh)
    return validate(recipe, str(path))


def discover(factory) -> dict[str, dict]:
    found: dict[str, dict] = {}
    if not factory.recipes_dir.exists():
        return found
    for path in sorted(factory.recipes_dir.rglob("*.json")):
        recipe = load_file(path)
        if recipe["id"] in found:
            raise RecipeError(f"duplicate recipe id {recipe['id']}: {path}")
        recipe["_source"] = str(path)
        found[recipe["id"]] = recipe
    return found


def load(factory, recipe_id: str) -> dict:
    recipes = discover(factory)
    if recipe_id not in recipes:
        raise RecipeError(f"recipe not found: {recipe_id}")
    return recipes[recipe_id]


def expand(value, ctx: dict):
    if isinstance(value, dict):
        return {k: expand(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [expand(v, ctx) for v in value]
    if isinstance(value, str):
        def repl(match: re.Match) -> str:
            key = match.group(1)
            if key not in ctx:
                raise RecipeError(f"unknown variable ${{{key}}}")
            return str(ctx[key])
        return _VAR.sub(repl, value)
    return value
