#!/usr/bin/env bash
#
# Build all MCP servers for Claude Copilot
#

set -euo pipefail

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Get the script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
MCP_SERVERS_DIR="$PROJECT_ROOT/mcp-servers"

# MCP servers to build
SERVERS=(
  "copilot-memory"
  "skills-copilot"
)

# Track build status
declare -A build_status
declare -a failed_servers

# Detect package manager
detect_package_manager() {
  if command -v pnpm &> /dev/null; then
    echo "pnpm"
  elif command -v yarn &> /dev/null; then
    echo "yarn"
  elif command -v npm &> /dev/null; then
    echo "npm"
  else
    echo ""
  fi
}

# Install dependencies for a server
install_dependencies() {
  local server_name="$1"
  local server_dir="$MCP_SERVERS_DIR/$server_name"
  local pm=$(detect_package_manager)

  if [ -z "$pm" ]; then
    echo -e "${RED}✗ No package manager found${NC}"
    return 1
  fi

  echo -e "${BLUE}Installing dependencies for $server_name...${NC}"

  cd "$server_dir"

  case "$pm" in
    pnpm)
      pnpm install --frozen-lockfile 2>&1 || pnpm install 2>&1
      ;;
    yarn)
      yarn install --frozen-lockfile 2>&1 || yarn install 2>&1
      ;;
    npm)
      npm ci 2>&1 || npm install 2>&1
      ;;
  esac

  return $?
}

# Build a server
build_server() {
  local server_name="$1"
  local server_dir="$MCP_SERVERS_DIR/$server_name"

  echo ""
  echo "========================================"
  echo "Building: $server_name"
  echo "========================================"

  # Check if server directory exists
  if [ ! -d "$server_dir" ]; then
    echo -e "${RED}✗ Server directory not found: $server_dir${NC}"
    build_status[$server_name]="missing"
    failed_servers+=("$server_name")
    return 1
  fi

  # Check if package.json exists
  if [ ! -f "$server_dir/package.json" ]; then
    echo -e "${RED}✗ package.json not found in $server_dir${NC}"
    build_status[$server_name]="invalid"
    failed_servers+=("$server_name")
    return 1
  fi

  # Install dependencies
  if ! install_dependencies "$server_name"; then
    echo -e "${RED}✗ Failed to install dependencies for $server_name${NC}"
    build_status[$server_name]="dep_failed"
    failed_servers+=("$server_name")
    return 1
  fi

  # Build the server
  echo -e "${BLUE}Building $server_name...${NC}"
  cd "$server_dir"

  if npm run build 2>&1; then
    echo -e "${GREEN}✓ $server_name built successfully${NC}"
    build_status[$server_name]="success"
    return 0
  else
    echo -e "${RED}✗ Build failed for $server_name${NC}"
    build_status[$server_name]="build_failed"
    failed_servers+=("$server_name")
    return 1
  fi
}

# Validate a build
validate_build() {
  local server_name="$1"
  local server_dir="$MCP_SERVERS_DIR/$server_name"
  local dist_dir="$server_dir/dist"

  # Check if dist directory exists
  if [ ! -d "$dist_dir" ]; then
    return 1
  fi

  # Check if index.js exists
  if [ ! -f "$dist_dir/index.js" ]; then
    return 1
  fi

  # Check if the file is not empty
  if [ ! -s "$dist_dir/index.js" ]; then
    return 1
  fi

  return 0
}

# Print build summary
print_summary() {
  echo ""
  echo "========================================"
  echo "Build Summary"
  echo "========================================"
  echo ""

  local total=${#SERVERS[@]}
  local successful=0
  local failed=0

  for server in "${SERVERS[@]}"; do
    if [ "${build_status[$server]}" == "success" ]; then
      echo -e "✓ ${GREEN}$server${NC}"
      ((successful++))
    else
      echo -e "✗ ${RED}$server${NC} (${build_status[$server]})"
      ((failed++))
    fi
  done

  echo ""
  echo "Total: $total | Success: $successful | Failed: $failed"
  echo ""

  if [ $failed -eq 0 ]; then
    echo -e "${GREEN}✓ All servers built successfully${NC}"
    echo "========================================"
    return 0
  else
    echo -e "${RED}✗ Some servers failed to build${NC}"
    echo ""
    echo "Failed servers:"
    for server in "${failed_servers[@]}"; do
      echo "  - $server"
    done
    echo "========================================"
    return 1
  fi
}

# Clean build artifacts
clean_builds() {
  echo "Cleaning build artifacts..."
  echo ""

  for server in "${SERVERS[@]}"; do
    local server_dir="$MCP_SERVERS_DIR/$server"
    if [ -d "$server_dir/dist" ]; then
      echo "Cleaning $server..."
      rm -rf "$server_dir/dist"
    fi
  done

  echo ""
  echo -e "${GREEN}✓ Build artifacts cleaned${NC}"
}

# Main execution
main() {
  local action="${1:-build}"
  local specific_server="${2:-}"

  case "$action" in
    build)
      if [ -n "$specific_server" ]; then
        # Build specific server
        build_server "$specific_server"
        if validate_build "$specific_server"; then
          echo -e "${GREEN}✓ Build validated${NC}"
          exit 0
        else
          echo -e "${RED}✗ Build validation failed${NC}"
          exit 1
        fi
      else
        # Build all servers
        for server in "${SERVERS[@]}"; do
          build_server "$server" || true
        done
        print_summary
      fi
      ;;

    validate)
      if [ -n "$specific_server" ]; then
        # Validate specific server
        if validate_build "$specific_server"; then
          echo -e "${GREEN}✓ $specific_server validated${NC}"
          exit 0
        else
          echo -e "${RED}✗ $specific_server validation failed${NC}"
          exit 1
        fi
      else
        # Validate all servers
        local all_valid=0
        for server in "${SERVERS[@]}"; do
          if validate_build "$server"; then
            echo -e "✓ ${GREEN}$server${NC}"
          else
            echo -e "✗ ${RED}$server${NC}"
            all_valid=1
          fi
        done
        exit $all_valid
      fi
      ;;

    clean)
      clean_builds
      ;;

    list)
      echo "Available MCP servers:"
      for server in "${SERVERS[@]}"; do
        echo "  - $server"
      done
      ;;

    --help)
      echo "Usage: $0 [build|validate|clean|list] [server-name]"
      echo ""
      echo "Commands:"
      echo "  build [server]    Build all servers or specific server"
      echo "  validate [server] Validate all builds or specific server"
      echo "  clean             Clean all build artifacts"
      echo "  list              List available servers"
      echo ""
      echo "Examples:"
      echo "  $0 build                    # Build all servers"
      echo "  $0 build copilot-memory     # Build specific server"
      echo "  $0 validate                 # Validate all builds"
      echo "  $0 clean                    # Clean artifacts"
      ;;

    *)
      echo "Unknown command: $action"
      echo "Run '$0 --help' for usage information"
      exit 1
      ;;
  esac
}

main "$@"
