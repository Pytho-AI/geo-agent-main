#!/usr/bin/env python3
"""
Load test data (military units and overlays) into the geo-agent database.

Usage:
    python scripts/load_test_data.py
    python scripts/load_test_data.py --file data/test/mil_units.json
    python scripts/load_test_data.py --overlays data/test/defense_overlays.json
    python scripts/load_test_data.py --all
"""

import os
import sys
import json
import uuid
import argparse
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

from sqlalchemy import create_engine, text

# Database connection
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://geoagent:geoagent@localhost:9846/geoagent"
)

# Default test map ID
DEFAULT_MAP_ID = "00000000-0000-0000-0000-000000000001"


def load_mil_units(engine, data: dict, map_id: str):
    """Load military units as entities into the database"""
    mil_units = data.get("mil_units", [])
    
    if not mil_units:
        print("No military units found in data file")
        return 0
    
    print(f"Loading {len(mil_units)} military units into map '{map_id}'...")
    
    with engine.connect() as conn:
        # Clear existing test mil_units for this map
        conn.execute(text("""
            DELETE FROM entities 
            WHERE kind = 'mil_unit' 
            AND map_id = CAST(:map_id AS uuid)
        """), {"map_id": map_id})
        
        # Insert each military unit as an entity
        for unit in mil_units:
            attrs = {
                "sidc": unit.get("sidc"),
                "name": unit.get("name"),
                "designation": unit.get("designation"),
                "echelon": unit.get("echelon"),
                "affiliation": unit.get("affiliation"),
                "status": unit.get("status"),
                "higherFormation": unit.get("higherFormation"),
                "strength": unit.get("strength"),
                "heading": unit.get("heading"),
            }
            
            conn.execute(text("""
                INSERT INTO entities (id, map_id, kind, geom, attrs, created_by)
                VALUES (
                    CAST(:id AS uuid),
                    CAST(:map_id AS uuid),
                    'mil_unit',
                    ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
                    CAST(:attrs AS jsonb),
                    'load_test_data'
                )
                ON CONFLICT (id) DO UPDATE SET
                    geom = EXCLUDED.geom,
                    attrs = EXCLUDED.attrs,
                    updated_at = NOW()
            """), {
                "id": unit["id"],
                "map_id": map_id,
                "lng": unit["lng"],
                "lat": unit["lat"],
                "attrs": json.dumps(attrs),
            })
        
        conn.commit()
    
    print(f"Successfully loaded {len(mil_units)} military units")
    return len(mil_units)


def load_overlays(engine, data: dict, map_id: str):
    """Load tactical overlays into the database"""
    overlays = data.get("overlays", [])
    
    if not overlays:
        print("No overlays found in data file")
        return 0
    
    print(f"Loading {len(overlays)} tactical overlays into map '{map_id}'...")
    
    with engine.connect() as conn:
        # Clear existing test overlays for this map (created by load_test_data)
        conn.execute(text("""
            DELETE FROM overlays 
            WHERE map_id = CAST(:map_id AS uuid)
            AND created_by = 'load_test_data'
        """), {"map_id": map_id})
        
        # Insert each overlay
        for overlay in overlays:
            overlay_id = str(uuid.uuid4())
            geometry = overlay.get("geometry", {})
            geom_type = geometry.get("type", "Point")
            coordinates = geometry.get("coordinates", [])
            
            # Build GeoJSON string for ST_GeomFromGeoJSON
            geojson = json.dumps(geometry)
            
            attrs = overlay.get("attrs", {})
            # Merge top-level attrs into attrs dict
            for key in ["designation", "affiliation", "echelon", "obstacleEffect", "remarks"]:
                if key in overlay and overlay[key]:
                    attrs[key] = overlay[key]
            
            conn.execute(text("""
                INSERT INTO overlays (id, map_id, kind, name, geom, attrs, created_by)
                VALUES (
                    CAST(:id AS uuid),
                    CAST(:map_id AS uuid),
                    :kind,
                    :name,
                    ST_SetSRID(ST_GeomFromGeoJSON(:geojson), 4326),
                    CAST(:attrs AS jsonb),
                    'load_test_data'
                )
            """), {
                "id": overlay_id,
                "map_id": map_id,
                "kind": overlay.get("kind", "area"),
                "name": overlay.get("name", overlay.get("designation")),
                "geojson": geojson,
                "attrs": json.dumps(attrs),
            })
        
        conn.commit()
    
    print(f"Successfully loaded {len(overlays)} tactical overlays")
    return len(overlays)


def main():
    parser = argparse.ArgumentParser(description="Load test data into geo-agent")
    parser.add_argument(
        "--file", "-f",
        default="data/test/mil_units.json",
        help="Path to military units JSON file"
    )
    parser.add_argument(
        "--overlays", "-o",
        default=None,
        help="Path to overlays JSON file"
    )
    parser.add_argument(
        "--map-id", "-m",
        default=DEFAULT_MAP_ID,
        help="Map ID to load data into (default: test map)"
    )
    parser.add_argument(
        "--all", "-a",
        action="store_true",
        help="Load all test data (mil_units + defense_overlays)"
    )
    args = parser.parse_args()
    
    # Find project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    
    # Connect to database
    print(f"Connecting to database...")
    engine = create_engine(DATABASE_URL)
    
    total_units = 0
    total_overlays = 0
    map_id = args.map_id
    
    # Load military units
    mil_units_file = project_root / args.file
    if mil_units_file.exists():
        print(f"Loading military units from: {mil_units_file}")
        with open(mil_units_file) as f:
            data = json.load(f)
        # Allow overriding map_id from file
        map_id = data.get("map_id", map_id)
        total_units = load_mil_units(engine, data, map_id)
    else:
        print(f"Warning: Military units file not found: {mil_units_file}")
    
    # Load overlays if specified or --all
    overlays_file = None
    if args.all:
        overlays_file = project_root / "data/test/defense_overlays.json"
    elif args.overlays:
        overlays_file = project_root / args.overlays
    
    if overlays_file and overlays_file.exists():
        print(f"\nLoading overlays from: {overlays_file}")
        with open(overlays_file) as f:
            overlay_data = json.load(f)
        total_overlays = load_overlays(engine, overlay_data, map_id)
    elif overlays_file:
        print(f"Warning: Overlays file not found: {overlays_file}")
    
    print(f"\nTest data loaded successfully!")
    print(f"  Military units: {total_units}")
    print(f"  Tactical overlays: {total_overlays}")
    print(f"  Map ID: {map_id}")


if __name__ == "__main__":
    main()
