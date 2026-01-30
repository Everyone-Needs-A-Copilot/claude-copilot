#!/usr/bin/env bash
#
# Linux-specific installation helpers
#

set -euo pipefail

# Color codes
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Detect Linux distribution
detect_distro() {
  if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "$ID"
  else
    echo "unknown"
  fi
}

# Check if package manager is available
check_package_manager() {
  local pm="$1"
  command -v "$pm" &> /dev/null
}

# Install Node.js on Debian/Ubuntu
install_node_debian() {
  echo "Installing Node.js on Debian/Ubuntu..."
  curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
  sudo apt-get install -y nodejs
  echo -e "${GREEN}✓ Node.js installed${NC}"
}

# Install Node.js on Fedora/RHEL/CentOS
install_node_fedora() {
  echo "Installing Node.js on Fedora/RHEL..."
  curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
  sudo dnf install -y nodejs
  echo -e "${GREEN}✓ Node.js installed${NC}"
}

# Install Node.js on Arch Linux
install_node_arch() {
  echo "Installing Node.js on Arch Linux..."
  sudo pacman -S --noconfirm nodejs npm
  echo -e "${GREEN}✓ Node.js installed${NC}"
}

# Install Git on Debian/Ubuntu
install_git_debian() {
  echo "Installing Git on Debian/Ubuntu..."
  sudo apt-get update
  sudo apt-get install -y git
  echo -e "${GREEN}✓ Git installed${NC}"
}

# Install Git on Fedora/RHEL/CentOS
install_git_fedora() {
  echo "Installing Git on Fedora/RHEL..."
  sudo dnf install -y git
  echo -e "${GREEN}✓ Git installed${NC}"
}

# Install Git on Arch Linux
install_git_arch() {
  echo "Installing Git on Arch Linux..."
  sudo pacman -S --noconfirm git
  echo -e "${GREEN}✓ Git installed${NC}"
}

# Provide installation instructions for missing dependencies
provide_install_instructions() {
  local missing_deps=("$@")
  local distro=$(detect_distro)

  echo ""
  echo "========================================"
  echo "Linux Installation Instructions"
  echo "========================================"
  echo ""
  echo "Detected distribution: $distro"
  echo ""

  for dep in "${missing_deps[@]}"; do
    case "$dep" in
      node)
        echo "Node.js 18+:"
        case "$distro" in
          ubuntu|debian)
            echo "  curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -"
            echo "  sudo apt-get install -y nodejs"
            ;;
          fedora|rhel|centos)
            echo "  curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -"
            echo "  sudo dnf install -y nodejs"
            ;;
          arch|manjaro)
            echo "  sudo pacman -S nodejs npm"
            ;;
          *)
            echo "  Install from: https://nodejs.org/"
            echo "  OR use nvm: https://github.com/nvm-sh/nvm"
            ;;
        esac
        echo ""
        ;;

      git)
        echo "Git:"
        case "$distro" in
          ubuntu|debian)
            echo "  sudo apt-get update"
            echo "  sudo apt-get install -y git"
            ;;
          fedora|rhel|centos)
            echo "  sudo dnf install -y git"
            ;;
          arch|manjaro)
            echo "  sudo pacman -S git"
            ;;
          *)
            echo "  Use your distribution's package manager to install git"
            ;;
        esac
        echo ""
        ;;

      claude)
        echo -e "${YELLOW}Claude CLI (optional):${NC}"
        echo "  Install from: https://github.com/anthropics/anthropic-quickstarts"
        echo "  Follow the installation instructions for your system"
        echo ""
        ;;
    esac
  done

  echo "========================================"
}

# Auto-install missing dependencies (interactive)
auto_install() {
  local distro=$(detect_distro)

  echo "Attempting to auto-install missing dependencies..."
  echo "Detected distribution: $distro"
  echo ""

  # Check Node.js
  if ! command -v node &> /dev/null; then
    echo "Installing Node.js..."
    case "$distro" in
      ubuntu|debian)
        install_node_debian
        ;;
      fedora|rhel|centos)
        install_node_fedora
        ;;
      arch|manjaro)
        install_node_arch
        ;;
      *)
        echo "Unsupported distribution for auto-install. Please install manually."
        provide_install_instructions node
        return 1
        ;;
    esac
  fi

  # Check Git
  if ! command -v git &> /dev/null; then
    echo "Installing Git..."
    case "$distro" in
      ubuntu|debian)
        install_git_debian
        ;;
      fedora|rhel|centos)
        install_git_fedora
        ;;
      arch|manjaro)
        install_git_arch
        ;;
      *)
        echo "Unsupported distribution for auto-install. Please install manually."
        provide_install_instructions git
        return 1
        ;;
    esac
  fi

  echo ""
  echo -e "${GREEN}✓ Auto-installation complete${NC}"
  return 0
}

# Main execution
main() {
  local action="${1:-help}"

  case "$action" in
    detect)
      detect_distro
      ;;
    install-node)
      local distro=$(detect_distro)
      case "$distro" in
        ubuntu|debian) install_node_debian ;;
        fedora|rhel|centos) install_node_fedora ;;
        arch|manjaro) install_node_arch ;;
        *) echo "Unsupported distribution"; exit 1 ;;
      esac
      ;;
    install-git)
      local distro=$(detect_distro)
      case "$distro" in
        ubuntu|debian) install_git_debian ;;
        fedora|rhel|centos) install_git_fedora ;;
        arch|manjaro) install_git_arch ;;
        *) echo "Unsupported distribution"; exit 1 ;;
      esac
      ;;
    auto-install)
      auto_install
      ;;
    instructions)
      shift
      provide_install_instructions "$@"
      ;;
    *)
      echo "Usage: $0 {detect|install-node|install-git|auto-install|instructions [deps...]}"
      echo ""
      echo "Commands:"
      echo "  detect           Detect Linux distribution"
      echo "  install-node     Install Node.js"
      echo "  install-git      Install Git"
      echo "  auto-install     Automatically install missing dependencies"
      echo "  instructions     Show manual installation instructions"
      ;;
  esac
}

main "$@"
