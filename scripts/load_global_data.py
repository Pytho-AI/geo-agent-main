#!/usr/bin/env python3
"""
Load global base data into geo-agent.

Datasets:
- Natural Earth: countries, states, rivers, lakes, roads, cities
- HydroSHEDS: river networks, watersheds (optional)
- Terrain: referenced via AWS Terrain Tiles (not stored locally)

Usage:
    # Load entire world
    python scripts/load_global_data.py
    
    # Load only area around a point (lat, lng, radius in km)
    python scripts/load_global_data.py --center 48.8566,2.3522 --radius 500
    
    # Load by bounding box (min_lon, min_lat, max_lon, max_lat)
    python scripts/load_global_data.py --bbox -10,35,30,60
"""

import os
import sys
import json
import math
import zipfile
import tempfile
import argparse
from pathlib import Path
from urllib.request import urlretrieve

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

import geopandas as gpd
from sqlalchemy import create_engine
from geoalchemy2 import Geometry
import fiona

# Data sources
NATURAL_EARTH_URL = "https://naciscdn.org/naturalearth/packages/natural_earth_vector.gpkg.zip"
HYDROSHEDS_RIVERS_URL = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_shp.zip"

# Natural Earth layers to load
NE_LAYERS = {
    # Countries & Admin
    "ne_10m_admin_0_countries": {"kind": "country", "name_field": "NAME"},
    "ne_10m_admin_1_states_provinces": {"kind": "state", "name_field": "name"},
    
    # Hydrology
    "ne_10m_rivers_lake_centerlines": {"kind": "river", "name_field": "name"},
    "ne_10m_lakes": {"kind": "lake", "name_field": "name"},
    
    # Infrastructure
    "ne_10m_roads": {"kind": "road", "name_field": "name"},
    "ne_10m_airports": {"kind": "airport", "name_field": "name"},
    "ne_10m_ports": {"kind": "port", "name_field": "name"},
    
    # Places
    "ne_10m_populated_places": {"kind": "city", "name_field": "NAME"},
}

# OSM region extracts (Geofabrik)
OSM_REGIONS = {
    "europe": "https://download.geofabrik.de/europe-latest.osm.pbf",
    "north-america": "https://download.geofabrik.de/north-america-latest.osm.pbf",
    "asia": "https://download.geofabrik.de/asia-latest.osm.pbf",
    "africa": "https://download.geofabrik.de/africa-latest.osm.pbf",
    # Smaller extracts for testing
    "luxembourg": "https://download.geofabrik.de/europe/luxembourg-latest.osm.pbf",
    "monaco": "https://download.geofabrik.de/europe/monaco-latest.osm.pbf",
}

# Default global map ID (for base layer data)
GLOBAL_MAP_ID = "00000000-0000-0000-0000-000000000000"


def download_file(url: str, dest: Path) -> Path:
    """Download file with progress"""
    print(f"Downloading {url}...")
    
    def progress(count, block_size, total_size):
        percent = int(count * block_size * 100 / total_size)
        sys.stdout.write(f"\r  {percent}%")
        sys.stdout.flush()
    
    urlretrieve(url, dest, reporthook=progress)
    print()
    return dest


def create_bbox_from_center(lat: float, lon: float, radius_km: float) -> tuple:
    """Create bounding box from center point and radius in km"""
    # Approximate degrees per km
    km_per_deg_lat = 111.0
    km_per_deg_lon = 111.0 * math.cos(math.radians(lat))
    
    delta_lat = radius_km / km_per_deg_lat
    delta_lon = radius_km / km_per_deg_lon
    
    return (
        lon - delta_lon,  # min_lon
        lat - delta_lat,  # min_lat
        lon + delta_lon,  # max_lon
        lat + delta_lat,  # max_lat
    )


def load_natural_earth(db_url: str, data_dir: Path, map_id: str, bbox: tuple = None):
    """Load Natural Earth data as entities
    
    Args:
        db_url: Database connection string
        data_dir: Directory to store downloaded files
        map_id: Map ID to load data into
        bbox: Optional (min_lon, min_lat, max_lon, max_lat) to filter data
    """
    
    gpkg_path = data_dir / "natural_earth_vector.gpkg"
    
    # Download if not exists
    if not gpkg_path.exists():
        zip_path = data_dir / "natural_earth_vector.gpkg.zip"
        if not zip_path.exists():
            download_file(NATURAL_EARTH_URL, zip_path)
        
        print("Extracting Natural Earth...")
        with zipfile.ZipFile(zip_path, 'r') as z:
            z.extractall(data_dir)
        
        # Find the gpkg file
        for f in data_dir.glob("**/*.gpkg"):
            gpkg_path = f
            break
    
    engine = create_engine(db_url.replace("+asyncpg", ""))
    
    if bbox:
        print(f"Filtering to bbox: {bbox}")
        from shapely.geometry import box
        bbox_geom = box(bbox[0], bbox[1], bbox[2], bbox[3])
    
    total_features = 0
    
    # Load each layer
    for layer_name, config in NE_LAYERS.items():
        try:
            print(f"Loading {layer_name}...")
            
            # Read with bbox filter if provided
            if bbox:
                gdf = gpd.read_file(gpkg_path, layer=layer_name, bbox=bbox)
            else:
                gdf = gpd.read_file(gpkg_path, layer=layer_name)
            
            if len(gdf) == 0:
                print(f"  No features in area, skipping")
                continue
            
            # Ensure geometry column is properly set (some files use 'geom' instead of 'geometry')
            if gdf.geometry is None or gdf.geometry.name not in gdf.columns:
                for col in gdf.columns:
                    if hasattr(gdf[col], 'geom_type'):
                        gdf = gdf.set_geometry(col)
                        break
            
            # Convert to WGS84 if needed
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)
            
            # Clip to bbox if provided (for features that extend beyond)
            if bbox:
                gdf = gdf.clip(bbox_geom)
                gdf = gdf[~gdf.geometry.is_empty]
            
            if len(gdf) == 0:
                print(f"  No features after clipping, skipping")
                continue
            
            # Simplify to reduce storage (tolerance in degrees, ~1km)
            gdf[gdf.geometry.name] = gdf.geometry.simplify(0.01)
            
            # Build attrs
            name_field = config.get("name_field", "name")
            gdf['kind'] = config['kind']
            gdf['map_id'] = map_id
            gdf['created_by'] = 'system'
            gdf['confidence'] = 1.0
            
            # Extract name to attrs
            if name_field in gdf.columns:
                gdf['attrs'] = gdf.apply(
                    lambda r: json.dumps({"name": r[name_field] if r[name_field] else ""}),
                    axis=1
                )
            else:
                gdf['attrs'] = '{}'
            
            # Select columns for entities table
            geom_col = gdf.geometry.name
            out_gdf = gdf[['kind', geom_col, 'attrs', 'confidence', 'map_id', 'created_by']].copy()
            out_gdf = out_gdf.rename(columns={geom_col: 'geom'})
            out_gdf = out_gdf.set_geometry('geom')
            
            # Write to database
            out_gdf.to_postgis(
                'entities',
                engine,
                if_exists='append',
                index=False,
                dtype={'geom': Geometry(srid=4326)}
            )
            
            print(f"  Loaded {len(out_gdf)} features")
            total_features += len(out_gdf)
            
        except Exception as e:
            print(f"  Skipping {layer_name}: {e}")
    
    print(f"\nNatural Earth data loaded! Total: {total_features} features")


def load_osm_region(db_url: str, data_dir: Path, region: str):
    """
    Load OpenStreetMap data for a region.
    
    Note: For large regions, this requires osmium/ogr2ogr tools.
    For MVP, we'll use smaller extracts or Overpass API.
    """
    if region not in OSM_REGIONS:
        print(f"Unknown region: {region}")
        print(f"Available: {', '.join(OSM_REGIONS.keys())}")
        return
    
    print(f"\nOSM loading for '{region}' requires additional tools (osmium, ogr2ogr).")
    print("For MVP, use the Overpass API or download GeoJSON extracts:")
    print(f"  https://overpass-turbo.eu/")
    print(f"  https://download.geofabrik.de/")
    print("\nAlternatively, upload OSM extracts via the /artifacts API.")


def print_terrain_info():
    """Print info about terrain data access"""
    print("""
Terrain Data (Elevation):
-------------------------
AWS Terrain Tiles provide global elevation data on-demand.
No download needed - query tiles at runtime.

Endpoint: https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png

Usage in code:
  from app.services.knowledge.terrain import get_elevation
  elevation = await get_elevation(lat=45.5, lon=-122.6)

For advanced terrain analysis (slope, viewshed, routes), you can:
1. Cache tiles locally for your area of interest
2. Use SRTM data from: https://earthexplorer.usgs.gov/
""")


def main():
    parser = argparse.ArgumentParser(description="Load global geo data")
    parser.add_argument("--db-url", default=os.getenv(
        "DATABASE_URL", 
        "postgresql://geoagent:geoagent@localhost:9846/geoagent"
    ))
    parser.add_argument("--data-dir", default="./data/global", type=Path)
    parser.add_argument("--map-id", default=GLOBAL_MAP_ID, help="Map ID for loaded data")
    parser.add_argument("--center", help="Center point as 'lat,lon' (e.g., 48.8566,2.3522)")
    parser.add_argument("--radius", type=float, default=500, help="Radius in km (default: 500)")
    parser.add_argument("--bbox", help="Bounding box as 'min_lon,min_lat,max_lon,max_lat'")
    parser.add_argument("--region", help="Also load OSM data for region")
    parser.add_argument("--terrain-info", action="store_true", help="Show terrain data info")
    
    args = parser.parse_args()
    
    # Create data directory
    args.data_dir.mkdir(parents=True, exist_ok=True)
    
    if args.terrain_info:
        print_terrain_info()
        return
    
    # Determine bounding box
    bbox = None
    if args.center:
        lat, lon = map(float, args.center.split(","))
        bbox = create_bbox_from_center(lat, lon, args.radius)
        print(f"Loading data for {args.radius}km around ({lat}, {lon})")
    elif args.bbox:
        bbox = tuple(map(float, args.bbox.split(",")))
        print(f"Loading data for bbox: {bbox}")
    else:
        print("Loading global data (use --center or --bbox to limit area)")
    
    # Load Natural Earth
    load_natural_earth(args.db_url, args.data_dir, args.map_id, bbox)
    
    # Optionally load OSM
    if args.region:
        load_osm_region(args.db_url, args.data_dir, args.region)
    
    # Print terrain info
    print_terrain_info()
    
    print("\n✓ Global data loading complete!")
    print("  Run: docker-compose up -d")
    print("  Then: python scripts/load_global_data.py")


if __name__ == "__main__":
    main()
