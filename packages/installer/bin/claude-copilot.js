#!/usr/bin/env node

/**
 * Claude Copilot CLI
 * Zero-config installer for Claude Copilot framework
 */

import { fileURLToPath } from 'url';
import { dirname, join } from 'path';
import { program } from 'commander';
import chalk from 'chalk';
import { install } from '../lib/install.js';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);

// Read package.json for version
import { readFileSync } from 'fs';
const packageJson = JSON.parse(
  readFileSync(join(__dirname, '../package.json'), 'utf-8')
);

program
  .name('claude-copilot')
  .description('Zero-config installer for Claude Copilot framework')
  .version(packageJson.version);

// Install command
program
  .command('install')
  .description('Install Claude Copilot framework')
  .option('-g, --global', 'Install globally to ~/.claude/copilot')
  .option('-p, --project <path>', 'Install to specific project directory')
  .option('--skip-deps', 'Skip dependency checks')
  .option('--skip-build', 'Skip building MCP servers')
  .option('--verbose', 'Show detailed output')
  .option('--auto-fix', 'Automatically fix missing dependencies')
  .action(async (options) => {
    try {
      console.log(chalk.blue.bold('\n🚀 Claude Copilot Installer\n'));

      const result = await install({
        global: options.global,
        projectPath: options.project,
        skipDeps: options.skipDeps,
        skipBuild: options.skipBuild,
        verbose: options.verbose,
        autoFix: options.autoFix,
      });

      if (result.success) {
        console.log(chalk.green.bold('\n✓ Installation completed successfully!\n'));

        if (result.nextSteps && result.nextSteps.length > 0) {
          console.log(chalk.yellow('Next steps:'));
          result.nextSteps.forEach((step, index) => {
            console.log(chalk.yellow(`  ${index + 1}. ${step}`));
          });
          console.log();
        }

        process.exit(0);
      } else {
        console.error(chalk.red.bold('\n✗ Installation failed\n'));

        if (result.errors && result.errors.length > 0) {
          console.error(chalk.red('Errors:'));
          result.errors.forEach(error => {
            console.error(chalk.red(`  - ${error}`));
          });
          console.log();
        }

        process.exit(1);
      }
    } catch (error) {
      console.error(chalk.red.bold('\n✗ Installation failed with error:\n'));
      console.error(chalk.red(error.message));
      if (options.verbose && error.stack) {
        console.error(chalk.gray('\nStack trace:'));
        console.error(chalk.gray(error.stack));
      }
      process.exit(1);
    }
  });

// Update command
program
  .command('update')
  .description('Update Claude Copilot to latest version')
  .option('-g, --global', 'Update global installation')
  .option('-p, --project <path>', 'Update specific project')
  .option('--verbose', 'Show detailed output')
  .action(async (options) => {
    console.log(chalk.blue('Updating Claude Copilot...'));
    console.log(chalk.yellow('Update functionality not yet implemented'));
    // TODO: Implement update logic
    process.exit(1);
  });

// Validate command
program
  .command('validate')
  .description('Validate Claude Copilot installation')
  .option('-p, --project <path>', 'Project directory to validate')
  .option('--verbose', 'Show detailed output')
  .action(async (options) => {
    console.log(chalk.blue('Validating installation...'));
    console.log(chalk.yellow('Validate functionality not yet implemented'));
    // TODO: Implement validation logic
    process.exit(1);
  });

// Check command
program
  .command('check')
  .description('Check system dependencies')
  .option('--json', 'Output as JSON')
  .option('--verbose', 'Show detailed output')
  .action(async (options) => {
    console.log(chalk.blue('Checking system dependencies...'));
    console.log(chalk.yellow('Check functionality not yet implemented'));
    // TODO: Implement check logic using check-dependencies.sh
    process.exit(1);
  });

// Parse CLI arguments
program.parse();

// Show help if no command provided
if (process.argv.length === 2) {
  program.help();
}
