#!/bin/bash

# Geo-Agent Development Script
# Usage: ./develop.sh [command]
#   ./develop.sh          - Start all services
#   ./develop.sh init     - Start services + load San Francisco data (100mi radius)
#   ./develop.sh db       - Start only database
#   ./develop.sh api      - Start only API (assumes db is running)
#   ./develop.sh stop     - Stop all services
#   ./develop.sh logs     - Show logs
#   ./develop.sh shell    - Open database shell

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Use docker compose (new) or docker-compose (old)
if command -v docker &> /dev/null && docker compose version &> /dev/null; then
    DOCKER_COMPOSE="docker compose"
else
    DOCKER_COMPOSE="docker-compose"
fi

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

case "${1:-all}" in
    db)
        echo -e "${GREEN}Starting database...${NC}"
        $DOCKER_COMPOSE up -d db
        echo -e "${GREEN}Database running on port 9846${NC}"
        ;;
    
    api)
        echo -e "${GREEN}Starting API server...${NC}"
        if [ -d "./venv" ]; then
            source ./venv/bin/activate
        elif [ -d "./virtual" ]; then
            source ./virtual/bin/activate
        fi
        cd backend
        uvicorn app.main:app --host 0.0.0.0 --port 9845 --reload
        ;;
    
    all)
        echo -e "${GREEN}Starting backend services...${NC}"
        $DOCKER_COMPOSE up -d
        
        echo ""
        echo -e "${GREEN}Services running:${NC}"
        echo -e "  API:      http://localhost:9845"
        echo -e "  Database: localhost:9846"
        echo ""
        echo -e "${YELLOW}To start frontend: ./develop.sh frontend${NC}"
        echo -e "${YELLOW}To view logs: ./develop.sh logs${NC}"
        ;;
    
    stop)
        echo -e "${YELLOW}Stopping all services...${NC}"
        $DOCKER_COMPOSE down
        ;;
    
    reset)
        echo -e "${YELLOW}Resetting database (deleting all data)...${NC}"
        $DOCKER_COMPOSE down -v
        docker volume rm geo-agent_postgres_data 2>/dev/null || true
        echo -e "${GREEN}Database reset. Run ./develop.sh to start fresh.${NC}"
        ;;
    
    logs)
        $DOCKER_COMPOSE logs -f
        ;;
    
    shell)
        echo -e "${GREEN}Opening database shell...${NC}"
        $DOCKER_COMPOSE exec db psql -U geoagent -d geoagent
        ;;
    
    load-data)
        echo -e "${GREEN}Loading global data...${NC}"
        
        # Setup Python virtual environment if it doesn't exist
        if [ ! -d "./venv" ]; then
            echo -e "${YELLOW}Creating Python virtual environment...${NC}"
            python3 -m venv venv
        fi
        
        # Activate virtual environment
        source ./venv/bin/activate
        
        # Install dependencies if not already installed
        if ! python3 -c "import geopandas" 2>/dev/null; then
            echo -e "${YELLOW}Installing Python dependencies...${NC}"
            pip install --upgrade pip
            pip install -r backend/requirements.txt
        fi
        
        python3 scripts/load_global_data.py "${@:2}"
        ;;
    
    load-test-data)
        echo -e "${GREEN}Loading test data (military units)...${NC}"
        
        # Setup Python virtual environment if it doesn't exist
        if [ ! -d "./venv" ]; then
            echo -e "${YELLOW}Creating Python virtual environment...${NC}"
            python3 -m venv venv
        fi
        
        # Activate virtual environment
        source ./venv/bin/activate
        
        # Install dependencies if not already installed
        if ! python3 -c "import sqlalchemy" 2>/dev/null; then
            echo -e "${YELLOW}Installing Python dependencies...${NC}"
            pip install --upgrade pip
            pip install -r backend/requirements.txt
        fi
        
        python3 scripts/load_test_data.py "${@:2}"
        ;;
    
    init)
        echo -e "${GREEN}Initializing geo-agent with San Francisco data (100 mile radius)...${NC}"
        
        # Setup Python virtual environment if it doesn't exist
        if [ ! -d "./venv" ]; then
            echo -e "${YELLOW}Creating Python virtual environment...${NC}"
            python3 -m venv venv
        fi
        
        # Activate virtual environment
        source ./venv/bin/activate
        
        # Install dependencies if not already installed
        if ! python3 -c "import geopandas" 2>/dev/null; then
            echo -e "${YELLOW}Installing Python dependencies...${NC}"
            pip install --upgrade pip
            pip install -r backend/requirements.txt
        fi
        
        # Start services
        echo -e "${GREEN}Starting Docker services...${NC}"
        $DOCKER_COMPOSE up -d
        
        # Wait for database to be ready
        echo -e "${YELLOW}Waiting for database to be ready...${NC}"
        for i in {1..30}; do
            if $DOCKER_COMPOSE exec -T db pg_isready -U geoagent -d geoagent >/dev/null 2>&1; then
                echo -e "${GREEN}Database is ready!${NC}"
                break
            fi
            echo "  Waiting for database... ($i/30)"
            sleep 2
        done
        
        # Wait a bit more for the API to fully initialize and run migrations
        echo -e "${YELLOW}Waiting for API to initialize...${NC}"
        sleep 5
        
        # San Francisco: 37.7749, -122.4194
        # 100 miles = ~161 km
        echo -e "${GREEN}Loading Natural Earth data for San Francisco area...${NC}"
        python3 scripts/load_global_data.py --center 37.7749,-122.4194 --radius 161
        
        echo ""
        echo -e "${GREEN}Initialization complete!${NC}"
        echo -e "  API:      http://localhost:9845"
        echo -e "  Database: localhost:9846"
        echo -e "  Data:     San Francisco area (100 mile radius)"
        echo ""
        echo -e "${YELLOW}To start frontend: ./develop.sh frontend${NC}"
        echo -e "${YELLOW}To view logs: ./develop.sh logs${NC}"
        ;;
    
    frontend)
        echo -e "${GREEN}Starting frontend dev server...${NC}"
        cd frontend
        npm install
        npm run dev
        ;;
    
    setup)
        echo -e "${GREEN}Setting up development environment...${NC}"
        
        # Create virtual environment
        if [ ! -d "./venv" ]; then
            python3 -m venv venv
        fi
        source ./venv/bin/activate
        
        # Install backend dependencies
        pip install -r backend/requirements.txt
        
        # Install frontend dependencies
        cd frontend && npm install && cd ..
        
        # Copy env file
        if [ ! -f ".env" ]; then
            cp .env.example .env 2>/dev/null || true
        fi
        
        echo -e "${GREEN}Setup complete!${NC}"
        echo -e "Run: ./develop.sh"
        ;;
    
    *)
        echo "Usage: ./develop.sh [command]"
        echo ""
        echo "Commands:"
        echo "  (none)     Start all services (docker-compose up)"
        echo "  init       Start services + load San Francisco data (100 mile radius)"
        echo "  db         Start only database"
        echo "  api        Start only API (requires venv, db must be running)"
        echo "  frontend   Start frontend dev server (port 3000)"
        echo "  stop       Stop all services"
        echo "  logs       Show docker logs"
        echo "  shell      Open database psql shell"
        echo "  load-data       Load global geo data (optional: --center lat,lon --radius km)"
        echo "  load-test-data  Load test military units into database"
        echo "  setup           Setup virtual environment and install dependencies"
        echo "  reset           Reset database (delete all data)"
        ;;
esac
