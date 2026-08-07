#!/usr/bin/env bash
#
# Dependency checker for Claude Copilot installation
# Outputs JSON status report of all required dependencies
#

set -euo pipefail

# Color codes for terminal output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Initialize JSON output structure
declare -A status
declare -A versions
declare -a errors
declare -a warnings

# Check Node.js version
check_node() {
  if command -v node &> /dev/null; then
    local node_version=$(node --version | sed 's/v//')
    local major_version=$(echo "$node_version" | cut -d. -f1)

    versions[node]="$node_version"

    if [ "$major_version" -ge 18 ]; then
      status[node]="ok"
    else
      status[node]="error"
      errors+=("Node.js version $node_version detected. Version 18+ required.")
    fi
  else
    status[node]="missing"
    errors+=("Node.js not found. Please install Node.js 18 or higher.")
  fi
}

# Check package manager (npm, pnpm, or yarn)
check_package_manager() {
  local found=0

  if command -v npm &> /dev/null; then
    versions[npm]=$(npm --version)
    status[npm]="ok"
    found=1
  else
    status[npm]="missing"
  fi

  if command -v pnpm &> /dev/null; then
    versions[pnpm]=$(pnpm --version)
    status[pnpm]="ok"
    found=1
  else
    status[pnpm]="missing"
  fi

  if command -v yarn &> /dev/null; then
    versions[yarn]=$(yarn --version)
    status[yarn]="ok"
    found=1
  else
    status[yarn]="missing"
  fi

  if [ $found -eq 0 ]; then
    errors+=("No package manager found. Please install npm, pnpm, or yarn.")
  fi
}

# Check Git version
check_git() {
  if command -v git &> /dev/null; then
    local git_version=$(git --version | sed 's/git version //')
    versions[git]="$git_version"
    status[git]="ok"
  else
    status[git]="missing"
    errors+=("Git not found. Please install Git.")
  fi
}

# Check Claude CLI
check_claude_cli() {
  if command -v claude &> /dev/null; then
    local claude_version=$(claude --version 2>&1 | head -n1 || echo "unknown")
    versions[claude]="$claude_version"
    status[claude]="ok"
  else
    status[claude]="missing"
    warnings+=("Claude CLI not found. Install from: https://github.com/anthropics/anthropic-quickstarts")
  fi
}

# Check platform-specific requirements
check_platform() {
  local platform=$(uname -s)

  case "$platform" in
    Darwin)
      status[platform]="macos"
      versions[platform]=$(sw_vers -productVersion 2>/dev/null || echo "unknown")
      ;;
    Linux)
      status[platform]="linux"
      if [ -f /etc/os-release ]; then
        versions[platform]=$(grep '^PRETTY_NAME=' /etc/os-release | cut -d'"' -f2)
      else
        versions[platform]="unknown"
      fi
      ;;
    *)
      status[platform]="unsupported"
      errors+=("Unsupported platform: $platform. Only macOS and Linux are supported.")
      ;;
  esac
}

# Build JSON output
build_json_output() {
  local healthy="true"

  # Check if there are any errors
  if [ ${#errors[@]} -gt 0 ]; then
    healthy="false"
  fi

  # Start JSON
  echo "{"
  echo "  \"healthy\": $healthy,"
  echo "  \"platform\": {"
  echo "    \"os\": \"${status[platform]}\","
  echo "    \"version\": \"${versions[platform]}\""
  echo "  },"
  echo "  \"dependencies\": {"

  # Node.js
  echo "    \"node\": {"
  echo "      \"status\": \"${status[node]}\","
  echo "      \"version\": \"${versions[node]:-null}\","
  echo "      \"required\": \"18+\""
  echo "    },"

  # Git
  echo "    \"git\": {"
  echo "      \"status\": \"${status[git]}\","
  echo "      \"version\": \"${versions[git]:-null}\""
  echo "    },"

  # Package managers
  echo "    \"packageManagers\": {"
  echo "      \"npm\": {"
  echo "        \"status\": \"${status[npm]}\","
  echo "        \"version\": \"${versions[npm]:-null}\""
  echo "      },"
  echo "      \"pnpm\": {"
  echo "        \"status\": \"${status[pnpm]}\","
  echo "        \"version\": \"${versions[pnpm]:-null}\""
  echo "      },"
  echo "      \"yarn\": {"
  echo "        \"status\": \"${status[yarn]}\","
  echo "        \"version\": \"${versions[yarn]:-null}\""
  echo "      }"
  echo "    },"

  # Claude CLI
  echo "    \"claude\": {"
  echo "      \"status\": \"${status[claude]}\","
  echo "      \"version\": \"${versions[claude]:-null}\""
  echo "    }"

  echo "  },"

  # Errors
  echo "  \"errors\": ["
  if [ ${#errors[@]} -gt 0 ]; then
    for i in "${!errors[@]}"; do
      echo -n "    \"${errors[$i]}\""
      if [ $i -lt $((${#errors[@]} - 1)) ]; then
        echo ","
      else
        echo ""
      fi
    done
  fi
  echo "  ],"

  # Warnings
  echo "  \"warnings\": ["
  if [ ${#warnings[@]} -gt 0 ]; then
    for i in "${!warnings[@]}"; do
      echo -n "    \"${warnings[$i]}\""
      if [ $i -lt $((${#warnings[@]} - 1)) ]; then
        echo ","
      else
        echo ""
      fi
    done
  fi
  echo "  ]"

  echo "}"
}

# Pretty print for human consumption
print_summary() {
  echo ""
  echo "========================================"
  echo "Claude Copilot Dependency Check"
  echo "========================================"
  echo ""

  echo -e "Platform: ${GREEN}${status[platform]}${NC} (${versions[platform]})"
  echo ""

  # Node.js
  if [ "${status[node]}" == "ok" ]; then
    echo -e "✓ Node.js: ${GREEN}${versions[node]}${NC}"
  elif [ "${status[node]}" == "missing" ]; then
    echo -e "✗ Node.js: ${RED}Not found${NC}"
  else
    echo -e "✗ Node.js: ${RED}${versions[node]} (18+ required)${NC}"
  fi

  # Git
  if [ "${status[git]}" == "ok" ]; then
    echo -e "✓ Git: ${GREEN}${versions[git]}${NC}"
  else
    echo -e "✗ Git: ${RED}Not found${NC}"
  fi

  # Package managers
  echo ""
  echo "Package Managers:"
  [ "${status[npm]}" == "ok" ] && echo -e "  ✓ npm: ${GREEN}${versions[npm]}${NC}" || echo -e "  ✗ npm: Not found"
  [ "${status[pnpm]}" == "ok" ] && echo -e "  ✓ pnpm: ${GREEN}${versions[pnpm]}${NC}" || echo -e "  ✗ pnpm: Not found"
  [ "${status[yarn]}" == "ok" ] && echo -e "  ✓ yarn: ${GREEN}${versions[yarn]}${NC}" || echo -e "  ✗ yarn: Not found"

  # Claude CLI
  echo ""
  if [ "${status[claude]}" == "ok" ]; then
    echo -e "✓ Claude CLI: ${GREEN}${versions[claude]}${NC}"
  else
    echo -e "○ Claude CLI: ${YELLOW}Not found (optional)${NC}"
  fi

  # Errors and warnings
  if [ ${#errors[@]} -gt 0 ]; then
    echo ""
    echo -e "${RED}Errors:${NC}"
    for error in "${errors[@]}"; do
      echo -e "  ${RED}✗${NC} $error"
    done
  fi

  if [ ${#warnings[@]} -gt 0 ]; then
    echo ""
    echo -e "${YELLOW}Warnings:${NC}"
    for warning in "${warnings[@]}"; do
      echo -e "  ${YELLOW}○${NC} $warning"
    done
  fi

  echo ""
  echo "========================================"

  if [ ${#errors[@]} -eq 0 ]; then
    echo -e "${GREEN}✓ All required dependencies met${NC}"
    echo "========================================"
    return 0
  else
    echo -e "${RED}✗ Missing required dependencies${NC}"
    echo "========================================"
    return 1
  fi
}

# Main execution
main() {
  local json_only=0
  local quiet=0

  # Parse arguments
  for arg in "$@"; do
    case "$arg" in
      --json)
        json_only=1
        ;;
      --quiet)
        quiet=1
        ;;
      --help)
        echo "Usage: $0 [--json] [--quiet] [--help]"
        echo ""
        echo "Options:"
        echo "  --json   Output JSON only (no pretty print)"
        echo "  --quiet  Suppress summary output"
        echo "  --help   Show this help message"
        exit 0
        ;;
    esac
  done

  # Run all checks
  check_platform
  check_node
  check_package_manager
  check_git
  check_claude_cli

  # Output results
  if [ $json_only -eq 1 ]; then
    build_json_output
  else
    if [ $quiet -eq 0 ]; then
      print_summary
      local exit_code=$?
      echo ""
      echo "JSON Output:"
    fi
    build_json_output
    [ $quiet -eq 0 ] && exit $exit_code
  fi
}

main "$@"
