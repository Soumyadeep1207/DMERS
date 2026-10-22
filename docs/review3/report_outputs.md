Reports run against the freshly reset demonstration data (the Review II history of 1-12 October 2026). Times are Asia/Kolkata.

### Active incidents, most severe first

Requirement FR-04 · Review II Q1 · selection, CASE inside ORDER BY  
Parameters: none

| id | title | severity | status |
|---|---|---|---|
| 7 | Palar river overflow near Vellore Fort | CRITICAL | RESPONDING |
| 10 | Rising water level at Anaicut check dam | HIGH | VERIFIED |
| 11 | Electrical fire in apartment block | HIGH | RESPONDING |
| 14 | Compound wall collapse after heavy rain | HIGH | RESPONDING |
| 9 | Waterlogging in Sathuvachari low-lying streets | MODERATE | VERIFIED |

5 row(s).

### Situation report by zone

Requirement FR-13 · Review II Q15 · VIEW v_zone_situation, scalar subquery, stored function fn_active_incidents  
Parameters: {'all_zones': False}

| zone_name | risk_level | active_incidents | units_available |
|---|---|---|---|
| Vellore Town | HIGH | 2 | 1 |
| Anaicut | MEDIUM | 1 | 0 |
| Pernambut | MEDIUM | 1 | 0 |
| Sathuvachari | HIGH | 1 | 0 |
| Gudiyatham | HIGH | 0 | 0 |

5 row(s).

### Command board for open incidents

Requirement FR-13 · Review II Q14 · two CTEs, left outer joins  
Parameters: none

| id | severity | on_scene | on_the_way | relief_items |
|---|---|---|---|---|
| 7 | CRITICAL | 2 | 1 | 6 |
| 9 | MODERATE | 0 | 0 | 2 |
| 10 | HIGH | 0 | 0 | 1 |
| 11 | HIGH | 1 | 0 | 0 |
| 14 | HIGH | 1 | 2 | 3 |

5 row(s).

### Relief stock status

Requirement FR-13 · Review II Q5 · stored function fn_stock_status in WHERE and SELECT  
Parameters: {'only_low': True}

| resource_name | available | reorder_level | stock_status |
|---|---|---|---|
| Inflatable rescue boats | 0 | 2 | OUT_OF_STOCK |
| Portable generators | 2 | 3 | LOW |
| Tarpaulin sheets | 50 | 60 | LOW |
| Water purification tablets | 80 | 100 | LOW |

4 row(s).

### Average response time per zone

Requirement FR-13 · Review II Q10 · AVG over the stored function fn_response_minutes  
Parameters: none

| zone_name | incidents_reached | avg_minutes |
|---|---|---|
| Katpadi | 2 | 16 |
| Ambur | 1 | 21 |
| Gudiyatham | 1 | 21 |
| Vellore Town | 2 | 31.5 |
| Sathuvachari | 1 | 32 |
| Walajapet | 1 | 54 |
| Pernambut | 1 | 58 |

7 row(s).

### Unit utilisation

Requirement FR-13 · Review II Q9 · join, GROUP BY, aggregate FILTER, interval arithmetic, LIMIT  
Parameters: {'limit': 5}

| unit_name | dispatches | completed | hours_on_scene |
|---|---|---|---|
| Gudiyatham Fire Unit | 2 | 1 | 3.48 |
| SDRF Team Alpha | 2 | 1 | 1.93 |
| Vellore Fire and Rescue | 2 | 1 | 1.88 |
| Ambulance AMB-03 | 2 | 1 | 0.65 |
| Ambulance VLR-01 | 2 | 0 |  |

5 row(s).

### Busiest unit of each type

Requirement FR-13 · Review II Q13 · derived table, window function ROW_NUMBER  
Parameters: none

| unit_type | unit_name | dispatches |
|---|---|---|
| FIRE | Gudiyatham Fire Unit | 2 |
| MEDICAL | Ambulance AMB-03 | 2 |
| POLICE | Katpadi Police Patrol | 1 |
| RELIEF | Relief Unit Gudiyatham | 1 |
| RESCUE | SDRF Team Alpha | 2 |

5 row(s).

### Incident timeline

Requirement FR-12 · Review II Q11 · left outer join, string expressions, to_char  
Parameters: {'incident_id': 3}

| no | logged_at | change | logged_by | note |
|---|---|---|---|---|
| 1 | 02-Oct 11:20 | - > REPORTED | Gopal Iyer | Incident reported |
| 2 | 02-Oct 11:26 | REPORTED > VERIFIED | Priya Natarajan | Status set to VERIFIED |
| 3 | 02-Oct 11:28 | VERIFIED > RESPONDING | Priya Natarajan | Status set to RESPONDING |
| 4 | 02-Oct 12:05 | RESPONDING > RESPONDING | Priya Natarajan | Allocated 20 First-aid kits |
| 5 | 02-Oct 13:30 | RESPONDING > RESPONDING | Priya Natarajan | Allocated 40 Tarpaulin sheets |
| 6 | 02-Oct 16:10 | RESPONDING > RESOLVED | Priya Natarajan | Status set to RESOLVED |
| 7 | 03-Oct 10:00 | RESOLVED > CLOSED | Priya Natarajan | Status set to CLOSED |

7 row(s).

### Everyone accountable for an incident

Requirement FR-12 · Review II Q12 · UNION of three joins  
Parameters: {'incident_id': 7}

| full_name | role |
|---|---|
| Priya Natarajan | dispatching coordinator |
| Rajesh Subramanian | dispatching coordinator |
| Arun Prakash | lead of a dispatched unit |
| Lakshmi Narayanan | lead of a dispatched unit |
| Mohammed Irfan | lead of a dispatched unit |
| Anitha Selvam | reporter |

6 row(s).

