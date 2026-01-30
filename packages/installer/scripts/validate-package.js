#!/usr/bin/env node

/**
 * Pre-publish validation script
 * Ensures package is ready for publication
 */

import { readFileSync, existsSync } from 'fs';
import { join, dirname } from 'path';
import { fileURLToPath } from 'url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = dirname(__filename);
const packageRoot = join(__dirname, '..');

function validate() {
  const errors = [];
  const warnings = [];

  // Check package.json
  const packageJsonPath = join(packageRoot, 'package.json');
  if (!existsSync(packageJsonPath)) {
    errors.push('package.json not found');
  } else {
    const pkg = JSON.parse(readFileSync(packageJsonPath, 'utf-8'));

    // Check required fields
    const requiredFields = ['name', 'version', 'description', 'main', 'bin', 'license'];
    for (const field of requiredFields) {
      if (!pkg[field]) {
        errors.push(`Missing required field: ${field}`);
      }
    }

    // Check bin entry
    if (pkg.bin && pkg.bin['claude-copilot']) {
      const binPath = join(packageRoot, pkg.bin['claude-copilot']);
      if (!existsSync(binPath)) {
        errors.push(`Bin file not found: ${pkg.bin['claude-copilot']}`);
      }
    }

    // Check main entry
    if (pkg.main) {
      const mainPath = join(packageRoot, pkg.main);
      if (!existsSync(mainPath)) {
        errors.push(`Main file not found: ${pkg.main}`);
      }
    }

    // Check files array
    if (pkg.files && pkg.files.length > 0) {
      for (const file of pkg.files) {
        const filePath = join(packageRoot, file);
        if (!existsSync(filePath)) {
          warnings.push(`File listed in 'files' not found: ${file}`);
        }
      }
    }
  }

  // Check README
  if (!existsSync(join(packageRoot, 'README.md'))) {
    warnings.push('README.md not found');
  }

  // Check LICENSE
  if (!existsSync(join(packageRoot, 'LICENSE'))) {
    warnings.push('LICENSE not found');
  }

  // Print results
  console.log('Package Validation Results:');
  console.log('===========================\n');

  if (errors.length === 0 && warnings.length === 0) {
    console.log('✓ All checks passed\n');
    return 0;
  }

  if (errors.length > 0) {
    console.log('Errors:');
    errors.forEach(error => console.log(`  ✗ ${error}`));
    console.log();
  }

  if (warnings.length > 0) {
    console.log('Warnings:');
    warnings.forEach(warning => console.log(`  ○ ${warning}`));
    console.log();
  }

  return errors.length > 0 ? 1 : 0;
}

const exitCode = validate();
process.exit(exitCode);
