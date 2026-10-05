"""Grid search algorithms used by the disaster response planner."""
from __future__ import annotations

import heapq
import itertools
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable

Point = tuple[int, int]
Grid = list[list[int]]
MOVES: tuple[Point, ...] = ((1, 0), (-1, 0), (0, 1), (0, -1))


@dataclass
class SearchResult:
    found: bool
    path: list[Point]
    visited: list[Point]
    frontier: list[Point]
    cost: float
    nodes_explored: int
    execution_time_ms: float
    memory_usage: int

    def as_dict(self) -> dict:
        return {"found": self.found, "path": self.path, "visited": self.visited,
                "frontier": self.frontier, "cost": self.cost,
                "nodesExplored": self.nodes_explored, "executionTime": self.execution_time_ms,
                "memoryUsage": self.memory_usage, "pathLength": max(0, len(self.path) - 1)}


def _valid(grid: Grid, p: Point) -> bool:
    r, c = p
    return 0 <= r < len(grid) and 0 <= c < len(grid[0]) and grid[r][c] >= 0


def _neighbors(grid: Grid, p: Point):
    for dr, dc in MOVES:
        q = p[0] + dr, p[1] + dc
        if _valid(grid, q):
            yield q


def _path(parents: dict[Point, Point | None], end: Point) -> list[Point]:
    answer = []
    while end is not None:
        answer.append(end)
        end = parents[end]
    return list(reversed(answer))


def search(grid: Grid, start: Point, goal: Point, algorithm: str) -> SearchResult:
    if not grid or not _valid(grid, start) or not _valid(grid, goal):
        raise ValueError("Start and goal must be valid passable grid cells")
    began = time.perf_counter()
    parents: dict[Point, Point | None] = {start: None}
    costs: dict[Point, float] = {start: 0}
    visited: list[Point] = []
    seen: set[Point] = {start}
    heuristic: Callable[[Point], int] = lambda p: abs(p[0] - goal[0]) + abs(p[1] - goal[1])
    counter = itertools.count()

    if algorithm == "bfs":
        frontier: deque[Point] | list[tuple[float, int, Point]] = deque([start])
        pop = frontier.popleft
        push = frontier.append
    elif algorithm == "dfs":
        frontier = [start]
        pop = frontier.pop
        push = frontier.append
    elif algorithm in {"ucs", "greedy", "astar"}:
        frontier = [(0, next(counter), start)]
        pop = lambda: heapq.heappop(frontier)[2]
        def push(p: Point) -> None:
            g = costs[p]
            priority = g if algorithm == "ucs" else heuristic(p) if algorithm == "greedy" else g + heuristic(p)
            heapq.heappush(frontier, (priority, next(counter), p))
    else:
        raise ValueError("Algorithm must be bfs, dfs, ucs, greedy, or astar")

    while frontier:
        current = pop()
        if current in visited:
            continue
        visited.append(current)
        if current == goal:
            elapsed = (time.perf_counter() - began) * 1000
            return SearchResult(True, _path(parents, goal), visited,
                [x if isinstance(x, tuple) and len(x) == 2 and isinstance(x[0], int) else x[2] for x in frontier],
                costs[goal], len(visited), round(elapsed, 3), len(seen) * 72)
        for nxt in _neighbors(grid, current):
            candidate = costs[current] + max(1, grid[nxt[0]][nxt[1]])
            if algorithm in {"ucs", "astar"} and candidate >= costs.get(nxt, float("inf")):
                continue
            if nxt not in seen or algorithm in {"ucs", "astar"}:
                seen.add(nxt); parents[nxt] = current; costs[nxt] = candidate; push(nxt)
    elapsed = (time.perf_counter() - began) * 1000
    return SearchResult(False, [], visited, [], 0, len(visited), round(elapsed, 3), len(seen) * 72)
