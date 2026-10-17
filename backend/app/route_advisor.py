"""Multi-factor response route planning on a small weighted road grid."""
from __future__ import annotations

from .search import search

MODE_WEIGHTS = {
    # Cell codes are: 1 normal, 2 poor road, 3 hazard area, -1 blocked.
    # All costs are relative grid units, not measured travel times.
    "fastest": {1: 1, 2: 1, 3: 2},
    "balanced": {1: 1, 2: 3, 3: 8},
    "safer": {1: 1, 2: 5, 3: 15},
}


def _weighted_grid(grid: list[list[int]], mode: str) -> list[list[int]]:
    weights = MODE_WEIGHTS[mode]
    return [[-1 if cell == -1 else weights[cell] for cell in row] for row in grid]


def _plan_all_targets(grid: list[list[int]], start: tuple[int, int], targets: list[tuple[int, int]], mode: str) -> dict:
    weighted = _weighted_grid(grid, mode)
    remaining = list(dict.fromkeys(targets))
    current = start
    path = [start]
    order = []
    cost = 0
    legs = []
    unreachable = []
    while remaining:
        choices = []
        for index, target in enumerate(remaining):
            result = search(weighted, current, target, "astar")
            if result.found:
                choices.append((result.cost, len(result.path), index, target, result))
        if not choices:
            unreachable = remaining
            break
        leg_cost, _, index, target, result = min(choices, key=lambda option: (option[0], option[1], option[2]))
        order.append(target)
        legs.append({"target": target, "cost": leg_cost, "steps": max(0, len(result.path) - 1)})
        path.extend(result.path[1:])
        cost += leg_cost
        current = target
        remaining.pop(index)

    poor = sum(1 for row, col in path[1:] if grid[row][col] == 2)
    hazard = sum(1 for row, col in path[1:] if grid[row][col] == 3)
    blocked = sum(1 for row, col in path if grid[row][col] == -1)
    return {
        "mode": mode, "path": path, "target_order": order, "legs": legs,
        "covered_targets": len(order), "total_targets": len(targets),
        "unreachable_targets": unreachable, "steps": max(0, len(path) - 1),
        "relative_cost": cost, "poor_road_cells": poor, "hazard_cells": hazard,
        "blocked_cells_on_path": blocked,
    }


def plan_response_route(
    grid: list[list[int]], start: tuple[int, int], targets: list[tuple[int, int]],
    mode: str, available_units: int, severity: str,
) -> dict:
    """Recommend route policy and compare fastest, balanced, and safer tours."""
    if not grid or len(grid) > 40 or not grid[0] or len(grid[0]) > 40:
        raise ValueError("Road grid must be between 1 and 40 rows and columns")
    width = len(grid[0])
    if any(len(row) != width for row in grid):
        raise ValueError("Road grid rows must have the same number of cells")
    if any(not isinstance(cell, int) or cell not in {-1, 1, 2, 3} for row in grid for cell in row):
        raise ValueError("Road cells must be -1 (blocked), 1 (normal), 2 (poor), or 3 (hazard)")
    if not 1 <= available_units <= 50:
        raise ValueError("Available response units must be between 1 and 50")
    if severity not in {"low", "moderate", "high", "critical"}:
        raise ValueError("Severity must be low, moderate, high, or critical")
    if mode not in {"auto", "fastest", "balanced", "safer"}:
        raise ValueError("Mode must be auto, fastest, balanced, or safer")
    if not targets or len(targets) > 12:
        raise ValueError("Provide between 1 and 12 target points")

    points = [start, *targets]
    if any(row < 0 or col < 0 or row >= len(grid) or col >= width for row, col in points):
        raise ValueError("Start and targets must be inside the road grid")
    if any(grid[row][col] == -1 for row, col in points):
        raise ValueError("Start and targets must be on passable cells")

    poor_count = sum(cell == 2 for row in grid for cell in row)
    hazard_count = sum(cell == 3 for row in grid for cell in row)
    blocked_count = sum(cell == -1 for row in grid for cell in row)
    if mode == "auto":
        if available_units <= 2:
            chosen = "fastest"
            reason = "Only a small response pool is available, so the plan favours rapid target coverage while keeping blocked cells impassable and hazards costlier than clear roads."
        elif severity in {"high", "critical"} or hazard_count >= 3:
            chosen = "safer"
            reason = "Resources allow a safety-first route, and incident severity or mapped hazards justify stronger avoidance of dangerous and poor-road cells."
        else:
            chosen = "balanced"
            reason = "The available response pool supports a balanced trade-off between route length and hazardous-road exposure."
    else:
        chosen = mode
        reason = {
            "fastest": "The operator selected fastest coverage. Poor roads are not penalised, hazards remain more costly, and blocked cells stay impassable.",
            "balanced": "The operator selected a middle ground between route length, poor roads, and hazardous cells.",
            "safer": "The operator selected safety-first routing, applying strong costs to hazards and poor roads while treating blocked cells as impassable.",
        }[mode]

    alternatives = {name: _plan_all_targets(grid, start, targets, name) for name in ("fastest", "balanced", "safer")}
    selected = alternatives[chosen]
    return {
        "recommended_mode": chosen,
        "reason": reason,
        "grid": grid,
        "start": start,
        "targets": targets,
        "selected_plan": selected,
        "alternatives": alternatives,
        "inputs": {
            "available_units": available_units, "severity": severity,
            "target_count": len(set(targets)), "poor_road_cells": poor_count,
            "hazard_cells": hazard_count, "blocked_cells": blocked_count,
        },
        "cost_legend": {"1": "clear road", "2": "poor road", "3": "hazard area", "-1": "blocked / never traversable"},
        "limitations": [
            "This uses a demonstration grid and relative cost units, not live road-network travel times.",
            "Only roads and hazards entered by the operator are represented; confirm them with field reports.",
            "The route and target order are recommendations. An authorised incident commander must review and approve deployment.",
        ],
    }
