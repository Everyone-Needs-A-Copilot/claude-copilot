# Zero-Config Installation Guide

**Status:** Ready for Testing
**Version:** 2.7.2

## Quick Start

### Option 1: NPM Package (Recommended)

```bash
# Install globally to ~/.claude/copilot
npx @copilot/installer install --global --auto-fix

# Or install to current project
npx @copilot/installer install --project . --auto-fix
```

### Option 2: From Source

```bash
# Clone the repository
git clone https://github.com/yourusername/claude-copilot.git
cd claude-copilot

# Make scripts executable
./scripts/install/make-executable.sh

# Check dependencies
./scripts/install/check-dependencies.sh

# Build MCP servers
./scripts/install/build-servers.sh build

# Validate installation
./scripts/install/validate-installation.sh
```

## Prerequisites

Before installation, ensure you have:

- **Node.js 18+** - Required for MCP servers
- **Git** - Required for version control
- **npm/pnpm/yarn** - At least one package manager
- **Claude CLI** - Optional but recommended

### Check Prerequisites

```bash
# Quick check
node --version  # Should be 18.0.0 or higher
git --version   # Any recent version
npm --version   # Any recent version

# Comprehensive check
./scripts/install/check-dependencies.sh
```

## Installation Methods

### Method 1: Global Installation

Installs framework to `~/.claude/copilot` for use across all projects.

```bash
# Using NPM package
npx @copilot/installer install --global --auto-fix --verbose

# Using source scripts
cd ~/.claude/copilot
git clone [repository-url] .
./scripts/install/make-executable.sh
./scripts/install/build-servers.sh build
```

**What gets installed:**
- Framework core files
- All 14 agents
- All commands
- 3 MCP servers (built and ready)
- Installation scripts
- Documentation

### Method 2: Project Installation

Installs framework files to specific project.

```bash
# Using NPM package
cd /path/to/your/project
npx @copilot/installer install --project . --auto-fix --verbose

# Using source scripts
# (Copy .claude/ directory and .mcp.json to project)
```

**What gets installed:**
- `.claude/` directory (agents, commands, skills)
- `.mcp.json` configuration
- `CLAUDE.md` project instructions
- References to global MCP servers

## Platform-Specific Setup

### macOS

**Auto-install dependencies:**
```bash
./scripts/install/platforms/macos.sh auto-install
```

**Manual installation:**
```bash
# Install Homebrew (if not installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install Node.js
brew install node@18

# Install Git
brew install git
```

### Linux (Debian/Ubuntu)

**Auto-install dependencies:**
```bash
./scripts/install/platforms/linux.sh auto-install
```

**Manual installation:**
```bash
# Install Node.js
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# Install Git
sudo apt-get update
sudo apt-get install -y git
```

### Linux (Fedora/RHEL)

**Auto-install dependencies:**
```bash
./scripts/install/platforms/linux.sh auto-install
```

**Manual installation:**
```bash
# Install Node.js
curl -fsSL https://rpm.nodesource.com/setup_18.x | sudo bash -
sudo dnf install -y nodejs

# Install Git
sudo dnf install -y git
```

### Linux (Arch)

**Auto-install dependencies:**
```bash
./scripts/install/platforms/linux.sh auto-install
```

**Manual installation:**
```bash
# Install Node.js and Git
sudo pacman -S nodejs npm git
```

## Building MCP Servers

The framework includes 3 MCP servers that need to be built:

1. **copilot-memory** - Persistent memory and semantic search
2. **task-copilot** - PRD and task management
3. **skills-copilot** - Skill loading and knowledge repositories

### Build All Servers

```bash
./scripts/install/build-servers.sh build
```

### Build Specific Server

```bash
./scripts/install/build-servers.sh build copilot-memory
```

### Validate Builds

```bash
./scripts/install/build-servers.sh validate
```

### Clean Builds

```bash
./scripts/install/build-servers.sh clean
```

## Validation

After installation, validate that everything is set up correctly:

```bash
# Using validation script
./scripts/install/validate-installation.sh

# Using NPM package
npx claude-copilot validate --project . --verbose
```

**Validation checks:**
- Framework structure (directories and files)
- All 14 agents present
- All 6 commands present
- All 3 MCP servers built
- Optional components (knowledge repo, skills)

## Troubleshooting

### Missing Dependencies

**Symptom:** Installation fails with dependency errors

**Solution:**
```bash
# Check what's missing
./scripts/install/check-dependencies.sh --verbose

# Auto-fix (macOS/Linux)
npx @copilot/installer install --global --auto-fix

# Or install manually using platform-specific instructions above
```

### Build Failures

**Symptom:** MCP servers fail to build

**Solution:**
```bash
# Check Node.js version (must be 18+)
node --version

# Try building individually to isolate issue
./scripts/install/build-servers.sh build copilot-memory
./scripts/install/build-servers.sh build task-copilot
./scripts/install/build-servers.sh build skills-copilot

# Check for detailed errors
./scripts/install/build-servers.sh build --verbose
```

### Permission Errors

**Symptom:** Permission denied errors

**Solution:**
```bash
# Make scripts executable
./scripts/install/make-executable.sh

# Or manually
chmod +x scripts/install/*.sh
chmod +x scripts/install/platforms/*.sh

# For global installation on Linux, may need sudo
sudo npx @copilot/installer install --global
```

### Package Manager Issues

**Symptom:** npm install fails or hangs

**Solution:**
```bash
# Clear npm cache
npm cache clean --force

# Try alternative package manager
npm install -g pnpm
# Then re-run installation

# Or use yarn
npm install -g yarn
# Then re-run installation
```

## Post-Installation

### Verify Installation

```bash
# Check all components
./scripts/install/validate-installation.sh

# Should see:
# Framework Structure: OK
# Agents: OK
# Commands: OK
# copilot-memory: OK
# task-copilot: OK
# skills-copilot: OK
```

### Configure MCP Servers

Update `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "copilot-memory": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/copilot-memory/dist/index.js"]
    },
    "task-copilot": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/task-copilot/dist/index.js"]
    },
    "skills-copilot": {
      "command": "node",
      "args": ["~/.claude/copilot/mcp-servers/skills-copilot/dist/index.js"]
    }
  }
}
```

### Start Using Claude Copilot

```bash
# In Claude Code, run:
/protocol your-task-description

# Or continue previous work:
/continue

# Check memory state:
/memory
```

## Advanced Options

### Skip Dependency Checks

If you've already verified dependencies:

```bash
npx @copilot/installer install --global --skip-deps
```

### Skip Building

If MCP servers are already built:

```bash
npx @copilot/installer install --global --skip-build
```

### Verbose Output

For detailed logging:

```bash
npx @copilot/installer install --global --verbose
```

### Development Installation

For framework development:

```bash
# Clone repository
git clone [repository-url] ~/.claude/copilot
cd ~/.claude/copilot

# Make scripts executable
./scripts/install/make-executable.sh

# Build servers in watch mode
cd mcp-servers/copilot-memory && npm run dev &
cd mcp-servers/task-copilot && npm run dev &
cd mcp-servers/skills-copilot && npm run dev &
```

## Getting Help

### Check Installation Status

```bash
# Comprehensive status
./scripts/install/validate-installation.sh

# Dependency status
./scripts/install/check-dependencies.sh

# Build status
./scripts/install/build-servers.sh validate
```

### Common Commands

```bash
# List available servers
./scripts/install/build-servers.sh list

# Clean and rebuild
./scripts/install/build-servers.sh clean
./scripts/install/build-servers.sh build

# Platform-specific help
./scripts/install/platforms/macos.sh --help
./scripts/install/platforms/linux.sh --help
```

## Next Steps

After successful installation:

1. **Initialize Project** - Run `/setup-project` in Claude Code
2. **Start First Task** - Run `/protocol your-task`
3. **Explore Features** - Try `/map`, `/orchestrate`, `/memory`
4. **Set Up Knowledge** - Run `/knowledge-copilot` for shared knowledge

## Updating

To update an existing installation:

```bash
# Update global installation
cd ~/.claude/copilot
git pull origin main
./scripts/install/build-servers.sh build

# Update project installation
cd /path/to/project
/update-project  # In Claude Code
```

## Uninstalling

To remove Claude Copilot:

```bash
# Remove global installation
rm -rf ~/.claude/copilot

# Remove project installation
rm -rf .claude/
rm .mcp.json
rm CLAUDE.md
```
