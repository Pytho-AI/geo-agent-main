-- Enable PostGIS extensions
CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS postgis_topology;

-- Maps table (map instances with viewport settings)
CREATE TABLE IF NOT EXISTS maps (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    user_id VARCHAR(255) NOT NULL,
    bbox_west FLOAT,
    bbox_south FLOAT,
    bbox_east FLOAT,
    bbox_north FLOAT,
    center_lng FLOAT,
    center_lat FLOAT,
    zoom FLOAT DEFAULT 8,
    attrs JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Insert default map for development (skip if already exists)
INSERT INTO maps (id, name, user_id, center_lng, center_lat, zoom) VALUES 
    ('00000000-0000-0000-0000-000000000001', 'Default Map', 'system', -122.4194, 37.7749, 8)
ON CONFLICT (id) DO NOTHING;

-- Entities table (units, features, POIs)
CREATE TABLE IF NOT EXISTS entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    map_id UUID NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    kind VARCHAR(50) NOT NULL,
    geom GEOMETRY(Geometry, 4326) NOT NULL,
    attrs JSONB DEFAULT '{}',
    confidence FLOAT DEFAULT 1.0,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Overlays table (phase lines, boundaries, routes)
CREATE TABLE IF NOT EXISTS overlays (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    map_id UUID NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    kind VARCHAR(50) NOT NULL,
    name VARCHAR(255),
    geom GEOMETRY(Geometry, 4326) NOT NULL,
    attrs JSONB DEFAULT '{}',
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Routes table (route planning requests with start/end points)
CREATE TABLE IF NOT EXISTS routes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    map_id UUID NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    name VARCHAR(255),
    start_geom GEOMETRY(Point, 4326) NOT NULL,
    end_geom GEOMETRY(Point, 4326) NOT NULL,
    route_mode VARCHAR(50) NOT NULL DEFAULT 'mixed',             -- on_road, off_road, mixed
    status VARCHAR(50) NOT NULL DEFAULT 'pending',             -- pending, computing, completed, failed
    attrs JSONB DEFAULT '{}',
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Route paths table (alternative paths within a route)
CREATE TABLE IF NOT EXISTS route_paths (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    route_id UUID NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    rank INTEGER NOT NULL DEFAULT 1,
    label VARCHAR(255),                 -- e.g. "Alpha", "Bravo", "Charlie"
    geom GEOMETRY(LineString, 4326) NOT NULL,
    selected INTEGER DEFAULT 0,         -- 0 = not selected, 1 = user-selected
    analysis JSONB DEFAULT '{}'          -- all route analysis (distance, time, elevation, terrain, etc.)
);

-- Custom symbols table (user-uploaded PNG/SVG icons for the map, global scope)
CREATE TABLE IF NOT EXISTS custom_symbols (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    file_format VARCHAR(10) NOT NULL,
    mime_type VARCHAR(100) NOT NULL,
    storage_uri VARCHAR(1024) NOT NULL,
    width INTEGER,
    height INTEGER,
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Artifacts table (uploaded files)
CREATE TABLE IF NOT EXISTS artifacts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    map_id UUID NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    filename VARCHAR(255) NOT NULL,
    file_type VARCHAR(50) NOT NULL,
    storage_uri VARCHAR(1024) NOT NULL,
    status VARCHAR(50) DEFAULT 'pending',
    file_meta JSONB DEFAULT '{}',
    created_by VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Events table (audit log)
CREATE TABLE IF NOT EXISTS events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    map_id UUID REFERENCES maps(id) ON DELETE SET NULL,
    op_type VARCHAR(50) NOT NULL,
    payload JSONB NOT NULL,
    actor VARCHAR(255),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Spatial indexes
CREATE INDEX IF NOT EXISTS idx_entities_geom ON entities USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_overlays_geom ON overlays USING GIST (geom);
CREATE INDEX IF NOT EXISTS idx_routes_start_geom ON routes USING GIST (start_geom);
CREATE INDEX IF NOT EXISTS idx_routes_end_geom ON routes USING GIST (end_geom);
CREATE INDEX IF NOT EXISTS idx_route_paths_geom ON route_paths USING GIST (geom);

-- Map indexes
CREATE INDEX IF NOT EXISTS idx_maps_user_id ON maps (user_id);
CREATE INDEX IF NOT EXISTS idx_entities_map_id ON entities (map_id);
CREATE INDEX IF NOT EXISTS idx_overlays_map_id ON overlays (map_id);
CREATE INDEX IF NOT EXISTS idx_routes_map_id ON routes (map_id);
CREATE INDEX IF NOT EXISTS idx_route_paths_route_id ON route_paths (route_id);
CREATE INDEX IF NOT EXISTS idx_artifacts_map_id ON artifacts (map_id);
CREATE INDEX IF NOT EXISTS idx_custom_symbols_created_at ON custom_symbols (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_map_id ON events (map_id);

-- Full-text search on attrs
CREATE INDEX IF NOT EXISTS idx_entities_attrs ON entities USING GIN (attrs);
CREATE INDEX IF NOT EXISTS idx_overlays_attrs ON overlays USING GIN (attrs);
CREATE INDEX IF NOT EXISTS idx_routes_attrs ON routes USING GIN (attrs);
CREATE INDEX IF NOT EXISTS idx_route_paths_analysis ON route_paths USING GIN (analysis);

-- Map history/snapshots table
CREATE TABLE IF NOT EXISTS map_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    map_id UUID NOT NULL REFERENCES maps(id) ON DELETE CASCADE,
    version INTEGER NOT NULL,
    label VARCHAR(255),
    map_snapshot JSONB NOT NULL,
    entities_snapshot JSONB NOT NULL DEFAULT '[]',
    overlays_snapshot JSONB NOT NULL DEFAULT '[]',
    artifacts_snapshot JSONB NOT NULL DEFAULT '[]',
    routes_snapshot JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMP DEFAULT NOW(),
    created_by VARCHAR(255),
    UNIQUE(map_id, version)
);
CREATE INDEX IF NOT EXISTS idx_map_history_map_id ON map_history(map_id);

-- Analyst-action audit + forwarded client logs (persistent telemetry —
-- survives container recreates on the postgres volume). Mirrors the
-- idempotent bootstrap in backend/app/main.py lifespan for existing DBs.
CREATE TABLE IF NOT EXISTS analyst_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    occurred_at_ms BIGINT,
    received_at_ms BIGINT NOT NULL,
    user_id VARCHAR(255),
    map_id VARCHAR(64),
    surface VARCHAR(64),
    event_type VARCHAR(128) NOT NULL,
    detail JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_analyst_events_map_time ON analyst_events (map_id, received_at_ms);
CREATE INDEX IF NOT EXISTS ix_analyst_events_type_time ON analyst_events (event_type, received_at_ms);
