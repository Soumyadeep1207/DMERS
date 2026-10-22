-- =====================================================================================
-- DMERS Incident-Response Database | BCSE302L Review II
-- 01_schema.sql : eight relations of the Review I design with all keys and constraints
-- PostgreSQL 16. Constraint names: pk_ primary key, fk_ foreign key, uq_ unique, ck_ check.
-- =====================================================================================
SET client_min_messages = warning;

CREATE TABLE users (
  id            INTEGER GENERATED ALWAYS AS IDENTITY
                CONSTRAINT pk_users PRIMARY KEY,
  full_name     VARCHAR(100) NOT NULL,
  account_type  VARCHAR(15) NOT NULL DEFAULT 'CITIZEN'
    CONSTRAINT ck_users_account_type CHECK (account_type
      IN ('CITIZEN', 'COORDINATOR', 'UNIT_LEAD',
          'ADMINISTRATOR')),
  email         VARCHAR(120) NOT NULL
    CONSTRAINT uq_users_email UNIQUE
    CONSTRAINT ck_users_email_format CHECK (email ~*
      '^[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}$'),
  password_hash TEXT NOT NULL,        -- hash only (BR-01)
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE zones (
  id            INTEGER GENERATED ALWAYS AS IDENTITY
                CONSTRAINT pk_zones PRIMARY KEY,
  zone_name     VARCHAR(60) NOT NULL
                CONSTRAINT uq_zones_name UNIQUE,
  district      VARCHAR(60) NOT NULL,
  state         VARCHAR(60) NOT NULL DEFAULT 'Tamil Nadu',
  risk_level    VARCHAR(6) NOT NULL
    CONSTRAINT ck_zones_risk_level
      CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH'))
);

CREATE TABLE incidents (
  id            INTEGER GENERATED ALWAYS AS IDENTITY
                CONSTRAINT pk_incidents PRIMARY KEY,
  title         VARCHAR(120) NOT NULL,
  description   TEXT,
  incident_type VARCHAR(30) NOT NULL,
  severity      VARCHAR(8) NOT NULL DEFAULT 'MODERATE'
    CONSTRAINT ck_incidents_severity CHECK (severity
      IN ('LOW', 'MODERATE', 'HIGH', 'CRITICAL')),
  status        VARCHAR(10) NOT NULL DEFAULT 'REPORTED'
    CONSTRAINT ck_incidents_status CHECK (status
      IN ('REPORTED', 'VERIFIED', 'RESPONDING',
          'RESOLVED', 'CLOSED', 'REJECTED')),
  location      VARCHAR(150) NOT NULL,
  zone_id       INTEGER           -- NULL until verified
    CONSTRAINT fk_incidents_zone
      REFERENCES zones (id) ON DELETE RESTRICT,
  reported_by   INTEGER NOT NULL
    CONSTRAINT fk_incidents_reporter
      REFERENCES users (id) ON DELETE RESTRICT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_incidents_zone_when_verified   -- FR-05
    CHECK (status IN ('REPORTED', 'REJECTED')
           OR zone_id IS NOT NULL),
  CONSTRAINT ck_incidents_timestamps
    CHECK (updated_at >= created_at)
);

CREATE TABLE response_units (
  id            INTEGER GENERATED ALWAYS AS IDENTITY
                CONSTRAINT pk_response_units PRIMARY KEY,
  unit_name     VARCHAR(60) NOT NULL
                CONSTRAINT uq_units_name UNIQUE,
  unit_type     VARCHAR(10) NOT NULL
    CONSTRAINT ck_units_type CHECK (unit_type IN
      ('FIRE', 'MEDICAL', 'POLICE', 'RESCUE', 'RELIEF')),
  contact_phone VARCHAR(10) NOT NULL
    CONSTRAINT ck_units_phone
      CHECK (contact_phone ~ '^[6-9][0-9]{9}$'),
  personnel_count SMALLINT NOT NULL
    CONSTRAINT ck_units_personnel
      CHECK (personnel_count > 0),
  availability_status VARCHAR(10) NOT NULL
    DEFAULT 'AVAILABLE'
    CONSTRAINT ck_units_availability
      CHECK (availability_status IN
        ('AVAILABLE', 'DEPLOYED', 'OFF_DUTY')),
  zone_id       INTEGER NOT NULL    -- total in BASED_IN
    CONSTRAINT fk_units_zone
      REFERENCES zones (id) ON DELETE RESTRICT,
  lead_user_id  INTEGER             -- optional 1:1 LEADS
    CONSTRAINT uq_units_lead UNIQUE
    CONSTRAINT fk_units_lead
      REFERENCES users (id) ON DELETE SET NULL
);

CREATE TABLE resources (
  id            INTEGER GENERATED ALWAYS AS IDENTITY
                CONSTRAINT pk_resources PRIMARY KEY,
  resource_name VARCHAR(60) NOT NULL
                CONSTRAINT uq_resources_name UNIQUE,
  category      VARCHAR(10) NOT NULL
    CONSTRAINT ck_resources_category CHECK (category IN
      ('FOOD', 'WATER', 'MEDICAL', 'SHELTER',
       'EQUIPMENT')),
  unit_of_measure VARCHAR(20) NOT NULL,
  quantity_available INTEGER NOT NULL DEFAULT 0
    CONSTRAINT ck_resources_quantity
      CHECK (quantity_available >= 0),
  reorder_level INTEGER NOT NULL DEFAULT 0
    CONSTRAINT ck_resources_reorder
      CHECK (reorder_level >= 0)
);

CREATE TABLE incident_updates (    -- weak INCIDENT_UPDATE
  incident_id   INTEGER NOT NULL
    CONSTRAINT fk_updates_incident
      REFERENCES incidents (id) ON DELETE CASCADE,
  update_no     INTEGER NOT NULL       -- partial key
    CONSTRAINT ck_updates_no CHECK (update_no >= 1),
  previous_status VARCHAR(10)
    CONSTRAINT ck_updates_previous_status
      CHECK (previous_status IN ('REPORTED', 'VERIFIED',
        'RESPONDING', 'RESOLVED', 'CLOSED', 'REJECTED')),
  new_status    VARCHAR(10) NOT NULL
    CONSTRAINT ck_updates_new_status
      CHECK (new_status IN ('REPORTED', 'VERIFIED',
        'RESPONDING', 'RESOLVED', 'CLOSED', 'REJECTED')),
  note          VARCHAR(200),
  logged_by     INTEGER         -- NULL: no signed-in user
    CONSTRAINT fk_updates_author
      REFERENCES users (id) ON DELETE RESTRICT,
  logged_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pk_incident_updates
    PRIMARY KEY (incident_id, update_no),
  CONSTRAINT ck_updates_first_entry
    CHECK ((update_no = 1) = (previous_status IS NULL))
);

CREATE TABLE dispatches (  -- ternary DISPATCHED_TO, M:N:1
  incident_id   INTEGER NOT NULL
    CONSTRAINT fk_dispatches_incident
      REFERENCES incidents (id) ON DELETE RESTRICT,
  unit_id       INTEGER NOT NULL
    CONSTRAINT fk_dispatches_unit
      REFERENCES response_units (id) ON DELETE RESTRICT,
  dispatched_by INTEGER NOT NULL  -- authorising official
    CONSTRAINT fk_dispatches_coordinator
      REFERENCES users (id) ON DELETE RESTRICT,
  dispatch_status VARCHAR(10) NOT NULL DEFAULT 'ASSIGNED'
    CONSTRAINT ck_dispatches_status
      CHECK (dispatch_status IN ('ASSIGNED', 'EN_ROUTE',
        'ON_SCENE', 'COMPLETED', 'CANCELLED')),
  dispatched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  arrived_at    TIMESTAMPTZ,
  cleared_at    TIMESTAMPTZ,
  CONSTRAINT pk_dispatches
    PRIMARY KEY (incident_id, unit_id),
  CONSTRAINT ck_dispatches_arrival               -- BR-06
    CHECK (arrived_at >= dispatched_at),
  CONSTRAINT ck_dispatches_clearance
    CHECK (cleared_at >=
           coalesce(arrived_at, dispatched_at)),
  CONSTRAINT ck_dispatches_arrived_on_scene
    CHECK (dispatch_status NOT IN ('ON_SCENE','COMPLETED')
           OR arrived_at IS NOT NULL),
  CONSTRAINT ck_dispatches_cleared_when_closed
    CHECK ((dispatch_status IN ('COMPLETED', 'CANCELLED'))
           = (cleared_at IS NOT NULL))
);

CREATE TABLE resource_allocations (       -- M:N ALLOCATED
  incident_id   INTEGER NOT NULL
    CONSTRAINT fk_allocations_incident
      REFERENCES incidents (id) ON DELETE RESTRICT,
  resource_id   INTEGER NOT NULL
    CONSTRAINT fk_allocations_resource
      REFERENCES resources (id) ON DELETE RESTRICT,
  quantity      INTEGER NOT NULL
    CONSTRAINT ck_allocations_quantity
      CHECK (quantity > 0),
  allocated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT pk_resource_allocations
    PRIMARY KEY (incident_id, resource_id)
);

-- BR-05 backstop: at most one active dispatch per unit
CREATE UNIQUE INDEX uq_dispatches_one_active_per_unit
  ON dispatches (unit_id)
  WHERE dispatch_status IN ('ASSIGNED', 'EN_ROUTE',
                            'ON_SCENE');

-- Indexes on foreign keys and the most frequent filter
CREATE INDEX ix_incidents_status_zone
  ON incidents (status, zone_id);
CREATE INDEX ix_incidents_reported_by
  ON incidents (reported_by);
CREATE INDEX ix_units_zone ON response_units (zone_id);
CREATE INDEX ix_dispatches_unit ON dispatches (unit_id);
CREATE INDEX ix_allocations_resource
  ON resource_allocations (resource_id);
