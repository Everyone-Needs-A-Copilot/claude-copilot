#!/usr/bin/env bash
#
# Post-installation validation for Claude Copilot
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

# Validation results
declare -A validation_results
declare -a validation_errors
declare -a validation_warnings

# Validate MCP server build
validate_mcp_server() {
  local server_name="$1"
  local server_dir="$PROJECT_ROOT/mcp-servers/$server_name"

  # Check server directory exists
  if [ ! -d "$server_dir" ]; then
    validation_results[$server_name]="missing"
    validation_errors+=("$server_name: Server directory not found")
    return 1
  fi

  # Check package.json exists
  if [ ! -f "$server_dir/package.json" ]; then
    validation_results[$server_name]="invalid"
    validation_errors+=("$server_name: package.json not found")
    return 1
  fi

  # Check dist directory exists
  if [ ! -d "$server_dir/dist" ]; then
    validation_results[$server_name]="not_built"
    validation_errors+=("$server_name: Not built (dist directory missing)")
    return 1
  fi

  # Check index.js exists
  if [ ! -f "$server_dir/dist/index.js" ]; then
    validation_results[$server_name]="incomplete"
    validation_errors+=("$server_name: Build incomplete (index.js missing)")
    return 1
  fi

  # Check if index.js is not empty
  if [ ! -s "$server_dir/dist/index.js" ]; then
    validation_results[$server_name]="empty"
    validation_errors+=("$server_name: Build invalid (index.js is empty)")
    return 1
  fi

  # Check node_modules exists
  if [ ! -d "$server_dir/node_modules" ]; then
    validation_results[$server_name]="no_deps"
    validation_warnings+=("$server_name: Dependencies not installed")
  fi

  validation_results[$server_name]="ok"
  return 0
}

# Validate framework structure
validate_framework_structure() {
  local errors=0

  echo "Validating framework structure..."

  # Check critical directories
  local required_dirs=(
    ".claude/agents"
    ".claude/commands"
    "mcp-servers"
    "scripts/install"
  )

  for dir in "${required_dirs[@]}"; do
    if [ ! -d "$PROJECT_ROOT/$dir" ]; then
      validation_errors+=("Framework: Missing directory $dir")
      ((errors++))
    fi
  done

  # Check critical files
  local required_files=(
    "CLAUDE.md"
    "SETUP.md"
    "package.json"
  )

  for file in "${required_files[@]}"; do
    if [ ! -f "$PROJECT_ROOT/$file" ]; then
      validation_errors+=("Framework: Missing file $file")
      ((errors++))
    fi
  done

  if [ $errors -eq 0 ]; then
    validation_results[framework]="ok"
    return 0
  else
    validation_results[framework]="incomplete"
    return 1
  fi
}

# Validate agents
validate_agents() {
  local agents_dir="$PROJECT_ROOT/.claude/agents"
  local errors=0

  echo "Validating agents..."

  # Expected agents
  local expected_agents=(
    "me.md"
    "ta.md"
    "qa.md"
    "sec.md"
    "doc.md"
    "do.md"
    "sd.md"
    "uxd.md"
    "uids.md"
    "uid.md"
    "cw.md"
    "cco.md"
    "kc.md"
  )

  for agent in "${expected_agents[@]}"; do
    if [ ! -f "$agents_dir/$agent" ]; then
      validation_errors+=("Agents: Missing agent $agent")
      ((errors++))
    fi
  done

  if [ $errors -eq 0 ]; then
    validation_results[agents]="ok"
    return 0
  else
    validation_results[agents]="incomplete"
    return 1
  fi
}

# Validate commands
validate_commands() {
  local commands_dir="$PROJECT_ROOT/.claude/commands"
  local errors=0

  echo "Validating commands..."

  # Expected commands
  local expected_commands=(
    "protocol.md"
    "continue.md"
    "pause.md"
    "map.md"
    "memory.md"
    "orchestrate.md"
  )

  for cmd in "${expected_commands[@]}"; do
    if [ ! -f "$commands_dir/$cmd" ]; then
      validation_errors+=("Commands: Missing command $cmd")
      ((errors++))
    fi
  done

  if [ $errors -eq 0 ]; then
    validation_results[commands]="ok"
    return 0
  else
    validation_results[commands]="incomplete"
    return 1
  fi
}

# Validate MCP servers
validate_mcp_servers() {
  echo "Validating MCP servers..."

  local servers=(
    "copilot-memory"
    "skills-copilot"
  )

  for server in "${servers[@]}"; do
    validate_mcp_server "$server" || true
  done
}

# Check for optional components
check_optional_components() {
  echo "Checking optional components..."

  # Check for knowledge repository
  if [ -d "$HOME/.claude/knowledge" ]; then
    validation_results[knowledge]="ok"
  else
    validation_results[knowledge]="not_installed"
    validation_warnings+=("Knowledge repository not found (optional)")
  fi

  # Check for skills directory
  if [ -d "$PROJECT_ROOT/.claude/skills" ]; then
    validation_results[skills]="ok"
  else
    validation_results[skills]="not_installed"
    validation_warnings+=("Skills directory not found (optional)")
  fi
}

# Print validation summary
print_summary() {
  echo ""
  echo "========================================"
  echo "Installation Validation Summary"
  echo "========================================"
  echo ""

  # Core components
  echo "Core Components:"
  echo -e "  Framework Structure: $(get_status_icon 'framework') $(get_status_text 'framework')"
  echo -e "  Agents: $(get_status_icon 'agents') $(get_status_text 'agents')"
  echo -e "  Commands: $(get_status_icon 'commands') $(get_status_text 'commands')"
  echo ""

  # MCP servers
  echo "MCP Servers:"
  echo -e "  copilot-memory: $(get_status_icon 'copilot-memory') $(get_status_text 'copilot-memory')"
  echo -e "  skills-copilot: $(get_status_icon 'skills-copilot') $(get_status_text 'skills-copilot')"
  echo ""

  # Optional components
  echo "Optional Components:"
  echo -e "  Knowledge Repository: $(get_status_icon 'knowledge') $(get_status_text 'knowledge')"
  echo -e "  Skills Directory: $(get_status_icon 'skills') $(get_status_text 'skills')"
  echo ""

  # Errors
  if [ ${#validation_errors[@]} -gt 0 ]; then
    echo -e "${RED}Errors:${NC}"
    for error in "${validation_errors[@]}"; do
      echo -e "  ${RED}✗${NC} $error"
    done
    echo ""
  fi

  # Warnings
  if [ ${#validation_warnings[@]} -gt 0 ]; then
    echo -e "${YELLOW}Warnings:${NC}"
    for warning in "${validation_warnings[@]}"; do
      echo -e "  ${YELLOW}○${NC} $warning"
    done
    echo ""
  fi

  # Overall status
  echo "========================================"
  if [ ${#validation_errors[@]} -eq 0 ]; then
    echo -e "${GREEN}✓ Installation validated successfully${NC}"
    echo "========================================"
    return 0
  else
    echo -e "${RED}✗ Installation validation failed${NC}"
    echo ""
    echo "Run the following to fix issues:"
    echo "  cd $PROJECT_ROOT"
    echo "  ./scripts/install/build-servers.sh build"
    echo "========================================"
    return 1
  fi
}

# Helper function to get status icon
get_status_icon() {
  local component="$1"
  local status="${validation_results[$component]:-unknown}"

  case "$status" in
    ok) echo -e "${GREEN}✓${NC}" ;;
    not_installed) echo -e "${YELLOW}○${NC}" ;;
    *) echo -e "${RED}✗${NC}" ;;
  esac
}

# Helper function to get status text
get_status_text() {
  local component="$1"
  local status="${validation_results[$component]:-unknown}"

  case "$status" in
    ok) echo -e "${GREEN}OK${NC}" ;;
    not_installed) echo -e "${YELLOW}Not installed${NC}" ;;
    missing) echo -e "${RED}Missing${NC}" ;;
    invalid) echo -e "${RED}Invalid${NC}" ;;
    not_built) echo -e "${RED}Not built${NC}" ;;
    incomplete) echo -e "${RED}Incomplete${NC}" ;;
    empty) echo -e "${RED}Empty${NC}" ;;
    no_deps) echo -e "${YELLOW}Missing dependencies${NC}" ;;
    *) echo -e "${RED}Unknown${NC}" ;;
  esac
}

# Main execution
main() {
  local json_only=0

  # Parse arguments
  for arg in "$@"; do
    case "$arg" in
      --json)
        json_only=1
        ;;
      --help)
        echo "Usage: $0 [--json] [--help]"
        echo ""
        echo "Options:"
        echo "  --json   Output JSON only"
        echo "  --help   Show this help message"
        exit 0
        ;;
    esac
  done

  # Run validations
  validate_framework_structure
  validate_agents
  validate_commands
  validate_mcp_servers
  check_optional_components

  # Print results
  if [ $json_only -eq 0 ]; then
    print_summary
    exit $?
  else
    # Output JSON (implement if needed)
    echo '{"status": "json_output_not_implemented"}'
    exit 1
  fi
}

main "$@"
