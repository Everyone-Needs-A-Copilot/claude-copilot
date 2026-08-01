#!/usr/bin/env bash
#
# macOS-specific installation helpers
#

set -euo pipefail

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check if Homebrew is installed
check_homebrew() {
  if command -v brew &> /dev/null; then
    echo "✓ Homebrew detected"
    return 0
  else
    echo "✗ Homebrew not found"
    return 1
  fi
}

# Install Node.js via Homebrew
install_node_homebrew() {
  echo "Installing Node.js via Homebrew..."
  brew install node@18
  echo -e "${GREEN}✓ Node.js installed${NC}"
}

# Install Git via Homebrew
install_git_homebrew() {
  echo "Installing Git via Homebrew..."
  brew install git
  echo -e "${GREEN}✓ Git installed${NC}"
}

# Provide installation instructions for missing dependencies
provide_install_instructions() {
  local missing_deps=("$@")

  echo ""
  echo "========================================"
  echo "macOS Installation Instructions"
  echo "========================================"
  echo ""

  for dep in "${missing_deps[@]}"; do
    case "$dep" in
      node)
        echo "Node.js 18+:"
        if check_homebrew; then
          echo "  Run: brew install node@18"
        else
          echo "  1. Install from: https://nodejs.org/ (download LTS version)"
          echo "  OR"
          echo "  2. Install Homebrew first: /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
          echo "     Then: brew install node@18"
        fi
        echo ""
        ;;

      git)
        echo "Git:"
        if check_homebrew; then
          echo "  Run: brew install git"
        else
          echo "  1. Install Xcode Command Line Tools: xcode-select --install"
          echo "  OR"
          echo "  2. Install from: https://git-scm.com/download/mac"
        fi
        echo ""
        ;;

      claude)
        echo -e "${YELLOW}Claude CLI (optional):${NC}"
        echo "  Install from: https://github.com/anthropics/anthropic-quickstarts"
        echo "  Follow the installation instructions for your system"
        echo ""
        ;;

      homebrew)
        echo "Homebrew (recommended):"
        echo "  /bin/bash -c \"\$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
        echo ""
        ;;
    esac
  done

  echo "========================================"
}

# Auto-install missing dependencies (interactive)
auto_install() {
  echo "Attempting to auto-install missing dependencies..."
  echo ""

  # Check for Homebrew
  if ! check_homebrew; then
    echo "Homebrew is required for auto-installation."
    echo "Would you like to install Homebrew? (y/N)"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
      /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    else
      echo "Skipping auto-installation. Please install dependencies manually."
      return 1
    fi
  fi

  # Check Node.js
  if ! command -v node &> /dev/null; then
    echo "Installing Node.js..."
    install_node_homebrew
  fi

  # Check Git
  if ! command -v git &> /dev/null; then
    echo "Installing Git..."
    install_git_homebrew
  fi

  echo ""
  echo -e "${GREEN}✓ Auto-installation complete${NC}"
  return 0
}

# Main execution
main() {
  local action="${1:-help}"

  case "$action" in
    check)
      check_homebrew
      ;;
    install-node)
      install_node_homebrew
      ;;
    install-git)
      install_git_homebrew
      ;;
    auto-install)
      auto_install
      ;;
    instructions)
      shift
      provide_install_instructions "$@"
      ;;
    *)
      echo "Usage: $0 {check|install-node|install-git|auto-install|instructions [deps...]}"
      echo ""
      echo "Commands:"
      echo "  check            Check if Homebrew is installed"
      echo "  install-node     Install Node.js via Homebrew"
      echo "  install-git      Install Git via Homebrew"
      echo "  auto-install     Automatically install missing dependencies"
      echo "  instructions     Show manual installation instructions"
      ;;
  esac
}

main "$@"
