# AI Algorithm Explanation

| Algorithm | Frontier | Completeness | Optimality | Best use |
|---|---|---|---|---|
| BFS | FIFO queue | Yes on finite grid | Yes with equal costs | Fewest steps |
| DFS | LIFO stack | Yes with visited set | No | Fast exploration demos |
| UCS | Cost priority queue | Yes | Yes with nonnegative costs | Variable road costs |
| Greedy | Heuristic priority queue | Yes on finite grid | No | Fast directional response |
| A* | `g(n)+h(n)` priority queue | Yes | Yes with admissible Manhattan heuristic | Default rescue routing |

Each cell has `(row, column)` coordinates and four directional actions. The Manhattan heuristic is `|r-goal_r| + |c-goal_c|`; it never overestimates a route on a four-neighbor unit-cost grid. The service records visited cells, remaining frontier, parent pointers, cost, elapsed time, and estimated frontier-memory bytes.

Planning repeatedly evaluates A* from the current team position to every remaining victim, chooses the least-cost reachable victim, then continues from that victim. This nearest-feasible heuristic is transparent and fast; it is a planning policy rather than a claim of globally optimal travelling-salesperson routing.
