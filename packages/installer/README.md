# Claude Copilot Installer

Zero-config installer for the Claude Copilot framework.

## Installation

```bash
# Install globally
npx @copilot/installer install --global

# Install to current project
npx @copilot/installer install --project .

# Install with auto-fix for missing dependencies
npx @copilot/installer install --global --auto-fix
```

## Usage

### Install Command

```bash
npx claude-copilot install [options]
```

**Options:**

- `-g, --global` - Install globally to `~/.claude/copilot`
- `-p, --project <path>` - Install to specific project directory
- `--skip-deps` - Skip dependency checks
- `--skip-build` - Skip building MCP servers
- `--verbose` - Show detailed output
- `--auto-fix` - Automatically fix missing dependencies

### Check Dependencies

```bash
npx claude-copilot check [options]
```

**Options:**

- `--json` - Output as JSON
- `--verbose` - Show detailed output

### Validate Installation

```bash
npx claude-copilot validate [options]
```

**Options:**

- `-p, --project <path>` - Project directory to validate
- `--verbose` - Show detailed output

## Requirements

- **Node.js** 18 or higher
- **Git** (any recent version)
- **npm**, **pnpm**, or **yarn** (any recent version)
- **Claude CLI** (optional, but recommended)

## What Gets Installed

### Global Installation (`--global`)

Installs to `~/.claude/copilot/`:

- Framework core files
- MCP servers (copilot-memory, skills-copilot)
- `tc` CLI (Task Copilot)
- Installation scripts
- Documentation

### Project Installation (`--project`)

Installs to project directory:

- `.claude/` directory (agents, commands, skills)
- `.mcp.json` configuration
- `CLAUDE.md` project instructions
- References to global MCP servers

## Platform Support

- **macOS** - Full support with Homebrew auto-install
- **Linux** - Full support (Debian/Ubuntu, Fedora/RHEL, Arch)
- **Windows** - Not yet supported

## Auto-Fix

The `--auto-fix` flag attempts to automatically install missing dependencies:

**macOS:**
- Installs Homebrew if missing
- Installs Node.js via Homebrew
- Installs Git via Homebrew

**Linux:**
- Detects distribution
- Uses appropriate package manager (apt, dnf, pacman)
- Installs Node.js and Git

## Examples

```bash
# Quick install with all features
npx @copilot/installer install --global --auto-fix --verbose

# Project install without dependency checks (dependencies already verified)
npx @copilot/installer install --project . --skip-deps

# Check what dependencies are missing
npx @copilot/installer check --verbose

# Validate existing installation
npx @copilot/installer validate --project .
```

## Troubleshooting

### Missing Dependencies

If installation fails due to missing dependencies:

1. Run `npx claude-copilot check --verbose` to see what's missing
2. Install missing dependencies manually
3. Or use `--auto-fix` to attempt automatic installation

### Build Failures

If MCP server builds fail:

1. Ensure Node.js 18+ is installed
2. Check that you have a working package manager
3. Try running the build script directly:
   ```bash
   cd ~/.claude/copilot
   ./scripts/install/build-servers.sh build
   ```

### Permission Issues

If you encounter permission errors:

- Use `sudo` for global installations on Linux
- Ensure you have write permissions to target directory
- Check that npm is configured correctly (`npm config get prefix`)

## Development

To test the installer locally:

```bash
cd packages/installer
npm link
claude-copilot install --global --verbose
```

## License

MIT
