/**
 * Main installation logic for Claude Copilot
 */

import { execSync, spawn } from 'child_process';
import { existsSync, mkdirSync, copyFileSync, chmodSync } from 'fs';
import { join, dirname, resolve } from 'path';
import { fileURLToPath } from 'url';
import { homedir } from 'os';
import chalk from 'chalk';
import ora from 'ora';
import prompts from 'prompts';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

/**
 * Get the framework root directory
 * When installed via npm, this will be in node_modules
 * When running from source, this will be the project root
 */
function getFrameworkRoot() {
  // Try to find the framework root by looking for CLAUDE.md
  let current = __dirname;
  for (let i = 0; i < 5; i++) {
    if (existsSync(join(current, 'CLAUDE.md'))) {
      return current;
    }
    current = dirname(current);
  }

  // Fallback: assume we're in packages/installer/lib
  return resolve(__dirname, '../../..');
}

/**
 * Check system dependencies
 */
async function checkDependencies(options = {}) {
  const spinner = ora('Checking system dependencies...').start();

  try {
    const frameworkRoot = getFrameworkRoot();
    const checkScript = join(frameworkRoot, 'scripts/install/check-dependencies.sh');

    if (!existsSync(checkScript)) {
      spinner.fail('Dependency check script not found');
      return { healthy: false, errors: ['check-dependencies.sh not found'] };
    }

    const result = execSync(`bash "${checkScript}" --json`, {
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe']
    });

    const status = JSON.parse(result);

    if (status.healthy) {
      spinner.succeed('System dependencies OK');
    } else {
      spinner.fail('Missing system dependencies');

      if (options.verbose) {
        console.log(chalk.yellow('\nDependency Status:'));
        console.log(JSON.stringify(status, null, 2));
      }
    }

    return status;
  } catch (error) {
    spinner.fail('Failed to check dependencies');
    if (options.verbose) {
      console.error(chalk.red(error.message));
    }
    return { healthy: false, errors: [error.message] };
  }
}

/**
 * Auto-fix missing dependencies
 */
async function autoFixDependencies(depStatus, options = {}) {
  const platform = depStatus.platform?.os;

  if (!platform || platform === 'unsupported') {
    console.log(chalk.red('Cannot auto-fix on unsupported platform'));
    return false;
  }

  const frameworkRoot = getFrameworkRoot();
  const platformScript = join(frameworkRoot, `scripts/install/platforms/${platform}.sh`);

  if (!existsSync(platformScript)) {
    console.log(chalk.red(`Platform script not found: ${platformScript}`));
    return false;
  }

  // Ask for confirmation
  const response = await prompts({
    type: 'confirm',
    name: 'confirm',
    message: 'Attempt to automatically install missing dependencies?',
    initial: true
  });

  if (!response.confirm) {
    return false;
  }

  const spinner = ora('Installing missing dependencies...').start();

  try {
    execSync(`bash "${platformScript}" auto-install`, {
      stdio: options.verbose ? 'inherit' : 'pipe'
    });

    spinner.succeed('Dependencies installed');
    return true;
  } catch (error) {
    spinner.fail('Failed to auto-install dependencies');
    if (options.verbose) {
      console.error(chalk.red(error.message));
    }
    return false;
  }
}

/**
 * Build MCP servers
 */
async function buildServers(options = {}) {
  const spinner = ora('Building MCP servers...').start();

  try {
    const frameworkRoot = getFrameworkRoot();
    const buildScript = join(frameworkRoot, 'scripts/install/build-servers.sh');

    if (!existsSync(buildScript)) {
      spinner.fail('Build script not found');
      return { success: false, errors: ['build-servers.sh not found'] };
    }

    execSync(`bash "${buildScript}" build`, {
      encoding: 'utf-8',
      stdio: options.verbose ? 'inherit' : 'pipe',
      cwd: frameworkRoot
    });

    spinner.succeed('MCP servers built successfully');
    return { success: true };
  } catch (error) {
    spinner.fail('Failed to build MCP servers');
    if (options.verbose) {
      console.error(chalk.red(error.message));
    }
    return { success: false, errors: [error.message] };
  }
}

/**
 * Validate installation
 */
async function validateInstallation(installPath, options = {}) {
  const spinner = ora('Validating installation...').start();

  try {
    const frameworkRoot = getFrameworkRoot();
    const validateScript = join(frameworkRoot, 'scripts/install/validate-installation.sh');

    if (!existsSync(validateScript)) {
      spinner.warn('Validation script not found (skipping)');
      return { success: true };
    }

    execSync(`bash "${validateScript}"`, {
      encoding: 'utf-8',
      stdio: options.verbose ? 'inherit' : 'pipe',
      cwd: installPath
    });

    spinner.succeed('Installation validated');
    return { success: true };
  } catch (error) {
    spinner.fail('Installation validation failed');
    if (options.verbose) {
      console.error(chalk.red(error.message));
    }
    return { success: false, errors: [error.message] };
  }
}

/**
 * Install to global location (~/.claude/copilot)
 */
async function installGlobal(options = {}) {
  const globalPath = join(homedir(), '.claude', 'copilot');
  const frameworkRoot = getFrameworkRoot();

  console.log(chalk.blue(`Installing to: ${globalPath}`));

  // Create directory if it doesn't exist
  if (!existsSync(globalPath)) {
    mkdirSync(globalPath, { recursive: true });
  }

  // Copy framework files (this is simplified - real implementation would be more thorough)
  const spinner = ora('Copying framework files...').start();

  try {
    // For now, just create a symlink or note
    // In production, this would copy all necessary files
    spinner.info('Global installation requires manual setup - see documentation');
    spinner.stop();

    return {
      success: true,
      installPath: globalPath,
      nextSteps: [
        `cd ${globalPath}`,
        'Run /setup in Claude Code'
      ]
    };
  } catch (error) {
    spinner.fail('Failed to install globally');
    return {
      success: false,
      errors: [error.message]
    };
  }
}

/**
 * Install to project directory
 */
async function installProject(projectPath, options = {}) {
  const targetPath = resolve(projectPath);

  console.log(chalk.blue(`Installing to project: ${targetPath}`));

  if (!existsSync(targetPath)) {
    console.log(chalk.yellow('Project directory does not exist. Creating...'));
    mkdirSync(targetPath, { recursive: true });
  }

  // In production, this would:
  // 1. Copy .claude directory
  // 2. Create .mcp.json
  // 3. Copy CLAUDE.md
  // 4. Set up MCP servers

  const spinner = ora('Setting up project...').start();
  spinner.info('Project installation requires manual setup - see documentation');
  spinner.stop();

  return {
    success: true,
    installPath: targetPath,
    nextSteps: [
      `cd ${targetPath}`,
      'Run /setup-project in Claude Code'
    ]
  };
}

/**
 * Main installation function
 */
export async function install(options = {}) {
  const {
    global = false,
    projectPath = null,
    skipDeps = false,
    skipBuild = false,
    verbose = false,
    autoFix = false
  } = options;

  const errors = [];
  const warnings = [];
  const nextSteps = [];

  // Step 1: Check dependencies
  if (!skipDeps) {
    const depStatus = await checkDependencies({ verbose });

    if (!depStatus.healthy) {
      console.log(chalk.yellow('\n⚠ Some dependencies are missing\n'));

      // Show errors
      if (depStatus.errors && depStatus.errors.length > 0) {
        console.log(chalk.red('Required:'));
        depStatus.errors.forEach(error => {
          console.log(chalk.red(`  - ${error}`));
        });
      }

      // Show warnings
      if (depStatus.warnings && depStatus.warnings.length > 0) {
        console.log(chalk.yellow('\nOptional:'));
        depStatus.warnings.forEach(warning => {
          console.log(chalk.yellow(`  - ${warning}`));
        });
      }

      // Try to auto-fix if requested
      if (autoFix) {
        const fixed = await autoFixDependencies(depStatus, { verbose });
        if (!fixed) {
          return {
            success: false,
            errors: ['Failed to auto-fix dependencies. Please install manually.'],
            nextSteps: ['Fix missing dependencies and try again']
          };
        }
      } else {
        return {
          success: false,
          errors: depStatus.errors,
          nextSteps: ['Install missing dependencies and try again', 'Or run with --auto-fix to attempt automatic installation']
        };
      }
    }
  } else {
    console.log(chalk.yellow('Skipping dependency checks (--skip-deps)'));
  }

  // Step 2: Build MCP servers
  if (!skipBuild) {
    const buildResult = await buildServers({ verbose });

    if (!buildResult.success) {
      return {
        success: false,
        errors: ['Failed to build MCP servers', ...(buildResult.errors || [])],
        nextSteps: ['Check build errors and try again']
      };
    }
  } else {
    console.log(chalk.yellow('Skipping MCP server builds (--skip-build)'));
  }

  // Step 3: Install to target location
  let installResult;

  if (global) {
    installResult = await installGlobal({ verbose });
  } else if (projectPath) {
    installResult = await installProject(projectPath, { verbose });
  } else {
    // Default: show usage
    return {
      success: false,
      errors: ['No installation target specified'],
      nextSteps: [
        'Use --global to install to ~/.claude/copilot',
        'Or use --project <path> to install to a specific project'
      ]
    };
  }

  if (!installResult.success) {
    return installResult;
  }

  // Step 4: Validate installation
  const validationResult = await validateInstallation(installResult.installPath, { verbose });

  if (!validationResult.success) {
    warnings.push('Installation validation failed (non-critical)');
  }

  // Combine next steps
  nextSteps.push(...(installResult.nextSteps || []));

  return {
    success: true,
    installPath: installResult.installPath,
    errors,
    warnings,
    nextSteps
  };
}

export default install;
