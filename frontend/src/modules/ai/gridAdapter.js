/**
 * Adapts the Command Centre's numeric training grid (1 = normal, -1 =
 * blocked, 2-3 = weighted poor road) into the canonical weighted-cell grid
 * {base, terrainWeight, hazard, exposure, blocked} the AI search/policy
 * modules operate on. The numeric grid predates the policy-aware cost model
 * and carries no hazard/exposure data, so both start at 0 here; a scenario
 * applied afterwards (flood/fire/earthquake) is what introduces hazard and
 * exposure.
 */
export function toCellGrid(numericGrid) {
  return numericGrid.map(row => row.map(value => ({
    base: 1,
    terrainWeight: value < 0 ? 1 : value,
    hazard: 0,
    exposure: 0,
    blocked: value < 0,
  })));
}
