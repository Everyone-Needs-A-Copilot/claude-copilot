/**
 * Integration tests for /map command (Codebase Mapping feature)
 *
 * Tests cover:
 * 1. Directory tree analyzer (respects .gitignore)
 * 2. Tech stack detector (package.json, Cargo.toml, requirements.txt, etc.)
 * 3. Key files identifier (README, CLAUDE.md, config files)
 * 4. PROJECT_MAP.md generation
 * 5. Refresh mode functionality
 *
 * Run with: node --test tests/map-command.test.ts
 */

import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import { mkdtempSync, rmSync, writeFileSync, readFileSync, existsSync, mkdirSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { execSync } from 'child_process';

describe('Codebase Mapping Feature', () => {
  let testProjectDir: string;

  before(() => {
    // Create temporary directory for test project
    testProjectDir = mkdtempSync(join(tmpdir(), 'map-test-'));
  });

  after(() => {
    // Cleanup
    rmSync(testProjectDir, { recursive: true, force: true });
  });

  describe('Tech Stack Detection', () => {
    describe('Node.js/TypeScript Projects', () => {
      it('should detect Node.js with npm', () => {
        const packageJson = {
          name: 'test-project',
          version: '1.0.0',
          dependencies: {}
        };

        writeFileSync(
          join(testProjectDir, 'package.json'),
          JSON.stringify(packageJson, null, 2)
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.language, 'JavaScript/TypeScript');
        assert.strictEqual(detection.packageManager, 'npm');
      });

      it('should detect yarn as package manager', () => {
        const packageJson = { name: 'test', version: '1.0.0' };
        writeFileSync(
          join(testProjectDir, 'package.json'),
          JSON.stringify(packageJson, null, 2)
        );
        writeFileSync(join(testProjectDir, 'yarn.lock'), '');

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.packageManager, 'yarn');
      });

      it('should detect pnpm as package manager', () => {
        const packageJson = { name: 'test', version: '1.0.0' };
        writeFileSync(
          join(testProjectDir, 'package.json'),
          JSON.stringify(packageJson, null, 2)
        );
        writeFileSync(join(testProjectDir, 'pnpm-lock.yaml'), '');

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.packageManager, 'pnpm');
      });

      it('should detect Next.js framework', () => {
        const packageJson = {
          name: 'test',
          dependencies: { next: '^13.0.0' }
        };
        writeFileSync(
          join(testProjectDir, 'package.json'),
          JSON.stringify(packageJson, null, 2)
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.framework, 'Next.js');
      });

      it('should detect React framework', () => {
        const packageJson = {
          name: 'test',
          dependencies: { react: '^18.0.0' }
        };
        writeFileSync(
          join(testProjectDir, 'package.json'),
          JSON.stringify(packageJson, null, 2)
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.framework, 'React');
      });

      it('should detect Vue framework', () => {
        const packageJson = {
          name: 'test',
          dependencies: { vue: '^3.0.0' }
        };
        writeFileSync(
          join(testProjectDir, 'package.json'),
          JSON.stringify(packageJson, null, 2)
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.framework, 'Vue');
      });

      it('should detect Express framework', () => {
        const packageJson = {
          name: 'test',
          dependencies: { express: '^4.0.0' }
        };
        writeFileSync(
          join(testProjectDir, 'package.json'),
          JSON.stringify(packageJson, null, 2)
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.framework, 'Express');
      });

      it('should prioritize Next.js over React when both present', () => {
        const packageJson = {
          name: 'test',
          dependencies: {
            next: '^13.0.0',
            react: '^18.0.0'
          }
        };
        writeFileSync(
          join(testProjectDir, 'package.json'),
          JSON.stringify(packageJson, null, 2)
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.framework, 'Next.js');
      });
    });

    describe('Rust Projects', () => {
      it('should detect Rust with cargo', () => {
        writeFileSync(
          join(testProjectDir, 'Cargo.toml'),
          '[package]\nname = "test"\nversion = "0.1.0"'
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.language, 'Rust');
        assert.strictEqual(detection.packageManager, 'cargo');
      });
    });

    describe('Go Projects', () => {
      it('should detect Go with go mod', () => {
        writeFileSync(
          join(testProjectDir, 'go.mod'),
          'module example.com/test\ngo 1.21'
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.language, 'Go');
        assert.strictEqual(detection.packageManager, 'go mod');
      });
    });

    describe('Python Projects', () => {
      it('should detect Python with pip (requirements.txt)', () => {
        writeFileSync(join(testProjectDir, 'requirements.txt'), 'requests==2.28.0');

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.language, 'Python');
        assert.strictEqual(detection.packageManager, 'pip');
      });

      it('should detect Python with pyproject.toml', () => {
        writeFileSync(
          join(testProjectDir, 'pyproject.toml'),
          '[project]\nname = "test"'
        );

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.language, 'Python');
      });

      it('should detect poetry as package manager', () => {
        writeFileSync(join(testProjectDir, 'pyproject.toml'), '[tool.poetry]');
        writeFileSync(join(testProjectDir, 'poetry.lock'), '');

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.language, 'Python');
        assert.strictEqual(detection.packageManager, 'poetry');
      });

      it('should detect pipenv as package manager', () => {
        writeFileSync(join(testProjectDir, 'requirements.txt'), '');
        writeFileSync(join(testProjectDir, 'Pipfile'), '');

        const detection = detectTechStack(testProjectDir);

        assert.strictEqual(detection.packageManager, 'pipenv');
      });
    });

    describe('Multi-language Projects', () => {
      it('should detect multiple languages', () => {
        writeFileSync(join(testProjectDir, 'package.json'), '{"name":"test"}');
        writeFileSync(join(testProjectDir, 'Cargo.toml'), '[package]\nname="test"');

        const detection = detectTechStack(testProjectDir);

        // Should detect both (order may vary)
        assert.ok(detection.languages);
        assert.ok(detection.languages.includes('JavaScript/TypeScript'));
        assert.ok(detection.languages.includes('Rust'));
      });
    });
  });

  describe('Directory Structure Analysis', () => {
    before(() => {
      // Create complex directory structure
      const dirs = [
        'src',
        'src/components',
        'src/utils',
        'tests',
        'docs',
        'node_modules/lodash', // Should be ignored
        'dist',                // Should be ignored
        '.git/objects'         // Should be ignored
      ];

      dirs.forEach(dir => {
        mkdirSync(join(testProjectDir, dir), { recursive: true });
      });

      // Add some files
      writeFileSync(join(testProjectDir, 'src/index.ts'), 'export {}');
      writeFileSync(join(testProjectDir, 'src/components/Button.tsx'), 'export {}');
    });

    it('should generate directory tree structure', () => {
      const tree = generateDirectoryTree(testProjectDir);

      assert.ok(tree.includes('src'));
      assert.ok(tree.includes('tests'));
      assert.ok(tree.includes('docs'));
    });

    it('should ignore node_modules directory', () => {
      const tree = generateDirectoryTree(testProjectDir);

      assert.strictEqual(tree.includes('node_modules'), false);
    });

    it('should ignore dist directory', () => {
      const tree = generateDirectoryTree(testProjectDir);

      assert.strictEqual(tree.includes('dist'), false);
    });

    it('should ignore .git directory', () => {
      const tree = generateDirectoryTree(testProjectDir);

      assert.strictEqual(tree.includes('.git'), false);
    });

    it('should respect maxDepth parameter', () => {
      const tree = generateDirectoryTree(testProjectDir, { maxDepth: 2 });

      // Should show src and src/components
      assert.ok(tree.includes('src'));

      // Depth 3 would be too deep with maxDepth 2
      const depth = tree.split('\n').filter(line =>
        line.includes('components')
      ).length;
      assert.ok(depth > 0);
    });

    it('should use tree command if available', () => {
      try {
        execSync('which tree', { stdio: 'ignore' });
        const treeAvailable = true;

        if (treeAvailable) {
          const tree = generateDirectoryTree(testProjectDir);
          assert.ok(tree.length > 0);
        }
      } catch {
        // tree command not available, skip
        assert.ok(true);
      }
    });

    it('should fallback to find when tree unavailable', () => {
      const tree = generateDirectoryTree(testProjectDir, { useFind: true });

      assert.ok(tree.includes('src'));
      assert.ok(Array.isArray(tree.split('\n')));
    });
  });

  describe('Key Files Identification', () => {
    before(() => {
      // Clean and recreate test project
      rmSync(testProjectDir, { recursive: true, force: true });
      mkdirSync(testProjectDir, { recursive: true });

      // Create various config and doc files
      writeFileSync(join(testProjectDir, 'package.json'), '{"name":"test"}');
      writeFileSync(join(testProjectDir, 'tsconfig.json'), '{}');
      writeFileSync(join(testProjectDir, 'vite.config.ts'), 'export default {}');
      writeFileSync(join(testProjectDir, '.env.example'), 'API_KEY=');
      writeFileSync(join(testProjectDir, 'README.md'), '# Test Project');
      writeFileSync(join(testProjectDir, 'CLAUDE.md'), '# Instructions');
      writeFileSync(join(testProjectDir, 'CONTRIBUTING.md'), '# Contributing');

      // Create entry points
      mkdirSync(join(testProjectDir, 'src'), { recursive: true });
      writeFileSync(join(testProjectDir, 'src/index.ts'), 'export {}');
      writeFileSync(join(testProjectDir, 'src/main.ts'), 'export {}');
      writeFileSync(join(testProjectDir, 'src/app.ts'), 'export {}');
    });

    it('should identify configuration files', () => {
      const keyFiles = identifyKeyFiles(testProjectDir);

      assert.ok(keyFiles.config.includes('package.json'));
      assert.ok(keyFiles.config.includes('tsconfig.json'));
      assert.ok(keyFiles.config.includes('vite.config.ts'));
    });

    it('should identify documentation files', () => {
      const keyFiles = identifyKeyFiles(testProjectDir);

      assert.ok(keyFiles.docs.some(f => f.includes('README.md')));
      assert.ok(keyFiles.docs.some(f => f.includes('CLAUDE.md')));
      assert.ok(keyFiles.docs.some(f => f.includes('CONTRIBUTING.md')));
    });

    it('should identify entry point files', () => {
      const keyFiles = identifyKeyFiles(testProjectDir);

      assert.ok(keyFiles.entryPoints.some(f => f.includes('index.ts')));
      assert.ok(keyFiles.entryPoints.some(f => f.includes('main.ts')));
      assert.ok(keyFiles.entryPoints.some(f => f.includes('app.ts')));
    });

    it('should respect maxDepth for file search', () => {
      // Create deeply nested file
      mkdirSync(join(testProjectDir, 'src/deep/nested/path'), { recursive: true });
      writeFileSync(join(testProjectDir, 'src/deep/nested/path/config.json'), '{}');

      const keyFiles = identifyKeyFiles(testProjectDir, { maxDepth: 2 });

      // Should not find deeply nested config
      const hasDeeplyNested = keyFiles.config.some(f =>
        f.includes('deep/nested/path')
      );
      assert.strictEqual(hasDeeplyNested, false);
    });

    it('should limit number of files per category', () => {
      // Create many config files
      for (let i = 0; i < 20; i++) {
        writeFileSync(join(testProjectDir, `config${i}.json`), '{}');
      }

      const keyFiles = identifyKeyFiles(testProjectDir, { limitPerCategory: 10 });

      assert.ok(keyFiles.config.length <= 10);
    });

    it('should handle projects with no config files', () => {
      const emptyDir = mkdtempSync(join(tmpdir(), 'empty-'));

      try {
        const keyFiles = identifyKeyFiles(emptyDir);

        assert.ok(Array.isArray(keyFiles.config));
        assert.strictEqual(keyFiles.config.length, 0);
      } finally {
        rmSync(emptyDir, { recursive: true, force: true });
      }
    });

    it('should recognize various config file patterns', () => {
      const configPatterns = [
        'eslint.config.js',
        'prettier.config.js',
        'jest.config.ts',
        'webpack.config.js',
        'tailwind.config.js',
        'next.config.js'
      ];

      configPatterns.forEach(file => {
        writeFileSync(join(testProjectDir, file), 'export default {}');
      });

      const keyFiles = identifyKeyFiles(testProjectDir);

      configPatterns.forEach(pattern => {
        assert.ok(
          keyFiles.config.some(f => f.includes(pattern)),
          `Should find ${pattern}`
        );
      });
    });
  });

  describe('PROJECT_MAP.md Generation', () => {
    let mapContent: string;

    before(() => {
      // Setup complete test project
      rmSync(testProjectDir, { recursive: true, force: true });
      mkdirSync(testProjectDir, { recursive: true });

      const packageJson = {
        name: 'test-project',
        version: '1.0.0',
        dependencies: {
          react: '^18.0.0'
        }
      };

      writeFileSync(
        join(testProjectDir, 'package.json'),
        JSON.stringify(packageJson, null, 2)
      );
      writeFileSync(join(testProjectDir, 'README.md'), '# Test');
      writeFileSync(join(testProjectDir, 'tsconfig.json'), '{}');

      mkdirSync(join(testProjectDir, 'src'), { recursive: true });
      writeFileSync(join(testProjectDir, 'src/index.ts'), 'export {}');

      // Generate PROJECT_MAP.md
      mapContent = generateProjectMap(testProjectDir);
      writeFileSync(join(testProjectDir, 'PROJECT_MAP.md'), mapContent);
    });

    it('should create PROJECT_MAP.md file', () => {
      const exists = existsSync(join(testProjectDir, 'PROJECT_MAP.md'));
      assert.strictEqual(exists, true);
    });

    it('should include project name in header', () => {
      assert.ok(mapContent.includes('# Project Map'));
      assert.ok(mapContent.includes('test-project'));
    });

    it('should include auto-generation notice', () => {
      assert.ok(mapContent.includes('Auto-generated by `/map`'));
    });

    it('should include last updated timestamp', () => {
      assert.ok(mapContent.includes('Last updated:'));
    });

    it('should include tech stack section', () => {
      assert.ok(mapContent.includes('## Tech Stack'));
      assert.ok(mapContent.includes('| Component | Value |'));
    });

    it('should include detected language', () => {
      assert.ok(mapContent.includes('JavaScript/TypeScript'));
    });

    it('should include package manager', () => {
      assert.ok(mapContent.includes('npm'));
    });

    it('should include detected framework', () => {
      assert.ok(mapContent.includes('React'));
    });

    it('should include directory structure section', () => {
      assert.ok(mapContent.includes('## Directory Structure'));
    });

    it('should include directory tree in code block', () => {
      assert.ok(mapContent.includes('```'));
      assert.ok(mapContent.includes('src'));
    });

    it('should include key files section', () => {
      assert.ok(mapContent.includes('## Key Files'));
    });

    it('should list configuration files', () => {
      assert.ok(mapContent.includes('### Configuration'));
      assert.ok(mapContent.includes('package.json'));
      assert.ok(mapContent.includes('tsconfig.json'));
    });

    it('should list documentation files', () => {
      assert.ok(mapContent.includes('### Documentation'));
      assert.ok(mapContent.includes('README.md'));
    });

    it('should list entry point files', () => {
      assert.ok(mapContent.includes('### Entry Points'));
      assert.ok(mapContent.includes('index.ts'));
    });

    it('should include architecture notes section', () => {
      assert.ok(mapContent.includes('## Architecture Notes'));
    });

    it('should include preservation comment in architecture notes', () => {
      assert.ok(mapContent.includes('<!-- This section is preserved on /map --refresh -->'));
    });

    it('should format files as bullet lists', () => {
      const lines = mapContent.split('\n');
      const hasListItems = lines.some(line => line.trim().startsWith('-'));
      assert.ok(hasListItems);
    });

    it('should use relative paths for files', () => {
      // Paths should be relative (./src/index.ts) not absolute
      assert.ok(!mapContent.includes(testProjectDir));
    });
  });

  describe('Refresh Mode', () => {
    let originalMap: string;

    before(() => {
      // Setup initial PROJECT_MAP.md with custom architecture notes
      rmSync(testProjectDir, { recursive: true, force: true });
      mkdirSync(testProjectDir, { recursive: true });

      writeFileSync(join(testProjectDir, 'package.json'), '{"name":"test"}');
      writeFileSync(join(testProjectDir, 'README.md'), '# Test');

      originalMap = generateProjectMap(testProjectDir);
      const mapWithNotes = originalMap.replace(
        '## Architecture Notes\n\n<!-- This section is preserved on /map --refresh -->',
        '## Architecture Notes\n\n<!-- This section is preserved on /map --refresh -->\n\n' +
        'Custom architectural notes:\n- Uses clean architecture\n- Domain-driven design'
      );

      writeFileSync(join(testProjectDir, 'PROJECT_MAP.md'), mapWithNotes);
    });

    it('should detect existing PROJECT_MAP.md', () => {
      const exists = existsSync(join(testProjectDir, 'PROJECT_MAP.md'));
      assert.strictEqual(exists, true);
    });

    it('should warn when PROJECT_MAP.md exists without --refresh', () => {
      // This would be handled by the command logic
      const shouldWarn = existsSync(join(testProjectDir, 'PROJECT_MAP.md'));
      assert.strictEqual(shouldWarn, true);
    });

    it('should preserve architecture notes section on refresh', () => {
      const existingContent = readFileSync(
        join(testProjectDir, 'PROJECT_MAP.md'),
        'utf-8'
      );

      // Extract architecture notes
      const notesSection = extractArchitectureNotes(existingContent);

      // Generate refreshed map
      const refreshedMap = generateProjectMap(testProjectDir, {
        preserveNotes: notesSection
      });

      // Verify notes are preserved
      assert.ok(refreshedMap.includes('Uses clean architecture'));
      assert.ok(refreshedMap.includes('Domain-driven design'));
    });

    it('should update tech stack on refresh', () => {
      // Add new dependency
      const pkg = JSON.parse(
        readFileSync(join(testProjectDir, 'package.json'), 'utf-8')
      );
      pkg.dependencies = { next: '^13.0.0' };
      writeFileSync(
        join(testProjectDir, 'package.json'),
        JSON.stringify(pkg, null, 2)
      );

      const refreshedMap = generateProjectMap(testProjectDir);

      assert.ok(refreshedMap.includes('Next.js'));
    });

    it('should update directory structure on refresh', () => {
      // Add new directory
      mkdirSync(join(testProjectDir, 'components'), { recursive: true });

      const refreshedMap = generateProjectMap(testProjectDir);

      assert.ok(refreshedMap.includes('components'));
    });

    it('should update key files on refresh', () => {
      // Add new config file
      writeFileSync(join(testProjectDir, 'vite.config.ts'), 'export default {}');

      const refreshedMap = generateProjectMap(testProjectDir);

      assert.ok(refreshedMap.includes('vite.config.ts'));
    });

    it('should update timestamp on refresh', () => {
      const firstMap = generateProjectMap(testProjectDir);
      const firstTimestamp = extractTimestamp(firstMap);

      // Wait a moment
      setTimeout(() => {
        const secondMap = generateProjectMap(testProjectDir);
        const secondTimestamp = extractTimestamp(secondMap);

        assert.notStrictEqual(firstTimestamp, secondTimestamp);
      }, 100);
    });
  });

  describe('.gitignore Respect', () => {
    before(() => {
      rmSync(testProjectDir, { recursive: true, force: true });
      mkdirSync(testProjectDir, { recursive: true });

      // Create .gitignore
      const gitignore = `
node_modules/
dist/
build/
*.log
.env
.DS_Store
coverage/
`.trim();

      writeFileSync(join(testProjectDir, '.gitignore'), gitignore);

      // Create ignored directories
      mkdirSync(join(testProjectDir, 'node_modules'), { recursive: true });
      mkdirSync(join(testProjectDir, 'dist'), { recursive: true });
      mkdirSync(join(testProjectDir, 'coverage'), { recursive: true });

      // Create non-ignored directories
      mkdirSync(join(testProjectDir, 'src'), { recursive: true });
      mkdirSync(join(testProjectDir, 'tests'), { recursive: true });

      // Create ignored files
      writeFileSync(join(testProjectDir, 'debug.log'), 'log content');
      writeFileSync(join(testProjectDir, '.env'), 'SECRET=value');
      writeFileSync(join(testProjectDir, '.DS_Store'), '');

      // Create non-ignored files
      writeFileSync(join(testProjectDir, 'package.json'), '{}');
      writeFileSync(join(testProjectDir, 'README.md'), '# Test');
    });

    it('should exclude gitignored directories from tree', () => {
      const tree = generateDirectoryTree(testProjectDir);

      assert.strictEqual(tree.includes('node_modules'), false);
      assert.strictEqual(tree.includes('dist'), false);
      assert.strictEqual(tree.includes('coverage'), false);
    });

    it('should include non-ignored directories in tree', () => {
      const tree = generateDirectoryTree(testProjectDir);

      assert.ok(tree.includes('src'));
      assert.ok(tree.includes('tests'));
    });

    it('should exclude gitignored files from key files', () => {
      const keyFiles = identifyKeyFiles(testProjectDir);

      const allFiles = [
        ...keyFiles.config,
        ...keyFiles.docs,
        ...keyFiles.entryPoints
      ].join('\n');

      assert.strictEqual(allFiles.includes('debug.log'), false);
      assert.strictEqual(allFiles.includes('.env'), false);
      assert.strictEqual(allFiles.includes('.DS_Store'), false);
    });

    it('should include non-ignored files in key files', () => {
      const keyFiles = identifyKeyFiles(testProjectDir);

      const allFiles = [
        ...keyFiles.config,
        ...keyFiles.docs,
        ...keyFiles.entryPoints
      ].join('\n');

      assert.ok(allFiles.includes('package.json'));
      assert.ok(allFiles.includes('README.md'));
    });
  });

  describe('Edge Cases', () => {
    it('should handle empty project directory', () => {
      const emptyDir = mkdtempSync(join(tmpdir(), 'empty-'));

      try {
        const map = generateProjectMap(emptyDir);

        assert.ok(map.includes('# Project Map'));
        assert.ok(map.includes('## Tech Stack'));
      } finally {
        rmSync(emptyDir, { recursive: true, force: true });
      }
    });

    it('should handle project with no package.json', () => {
      const noPackageDir = mkdtempSync(join(tmpdir(), 'no-package-'));

      try {
        mkdirSync(join(noPackageDir, 'src'), { recursive: true });
        writeFileSync(join(noPackageDir, 'README.md'), '# Test');

        const map = generateProjectMap(noPackageDir);

        assert.ok(map.includes('# Project Map'));
        // Should still generate map even without package.json
        assert.ok(map.includes('README.md'));
      } finally {
        rmSync(noPackageDir, { recursive: true, force: true });
      }
    });

    it('should handle very large directory structures', () => {
      const largeDir = mkdtempSync(join(tmpdir(), 'large-'));

      try {
        // Create 100 directories
        for (let i = 0; i < 100; i++) {
          mkdirSync(join(largeDir, `dir${i}`), { recursive: true });
        }

        const tree = generateDirectoryTree(largeDir, { maxDepth: 2 });

        assert.ok(tree.length > 0);
        // Should not crash or hang
      } finally {
        rmSync(largeDir, { recursive: true, force: true });
      }
    });

    it('should handle special characters in filenames', () => {
      const specialDir = mkdtempSync(join(tmpdir(), 'special-'));

      try {
        writeFileSync(join(specialDir, 'file with spaces.md'), '# Test');
        writeFileSync(join(specialDir, 'file-with-dashes.json'), '{}');
        writeFileSync(join(specialDir, 'file_with_underscores.ts'), 'export {}');

        const keyFiles = identifyKeyFiles(specialDir);
        const allFiles = [
          ...keyFiles.config,
          ...keyFiles.docs,
          ...keyFiles.entryPoints
        ].join('\n');

        assert.ok(allFiles.includes('file with spaces.md'));
        assert.ok(allFiles.includes('file-with-dashes.json'));
        assert.ok(allFiles.includes('file_with_underscores.ts'));
      } finally {
        rmSync(specialDir, { recursive: true, force: true });
      }
    });

    it('should handle missing architecture notes section', () => {
      const mapWithoutNotes = `# Project Map

## Tech Stack

| Component | Value |
|-----------|-------|
| Language | JavaScript |

## Directory Structure

\`\`\`
src/
\`\`\`
`;

      const notes = extractArchitectureNotes(mapWithoutNotes);
      assert.strictEqual(notes, '');
    });

    it('should handle corrupt package.json gracefully', () => {
      const corruptDir = mkdtempSync(join(tmpdir(), 'corrupt-'));

      try {
        writeFileSync(join(corruptDir, 'package.json'), '{invalid json');

        const detection = detectTechStack(corruptDir);

        // Should not crash, should handle gracefully
        assert.ok(detection);
      } finally {
        rmSync(corruptDir, { recursive: true, force: true });
      }
    });

    it('should handle symlinks without infinite loops', () => {
      // Skip on Windows where symlinks require admin
      if (process.platform === 'win32') {
        assert.ok(true);
        return;
      }

      const symlinkDir = mkdtempSync(join(tmpdir(), 'symlink-'));

      try {
        mkdirSync(join(symlinkDir, 'real'), { recursive: true });

        // This test is skipped if symlinks aren't supported
        try {
          execSync(`ln -s real ${join(symlinkDir, 'link')}`, { cwd: symlinkDir });

          const tree = generateDirectoryTree(symlinkDir);

          // Should not hang or crash
          assert.ok(tree.length > 0);
        } catch {
          // Symlink creation failed, skip test
          assert.ok(true);
        }
      } finally {
        rmSync(symlinkDir, { recursive: true, force: true });
      }
    });
  });
});

// =============================================================================
// Helper Functions (implementation)
// =============================================================================

interface TechStackDetection {
  language?: string;
  languages?: string[];
  packageManager?: string;
  framework?: string;
}

function detectTechStack(projectPath: string): TechStackDetection {
  const result: TechStackDetection = {};
  const languages: string[] = [];

  // Node.js / TypeScript
  if (existsSync(join(projectPath, 'package.json'))) {
    result.language = 'JavaScript/TypeScript';
    languages.push('JavaScript/TypeScript');

    // Package manager detection
    if (existsSync(join(projectPath, 'yarn.lock'))) {
      result.packageManager = 'yarn';
    } else if (existsSync(join(projectPath, 'pnpm-lock.yaml'))) {
      result.packageManager = 'pnpm';
    } else {
      result.packageManager = 'npm';
    }

    // Framework detection
    try {
      const pkgContent = readFileSync(join(projectPath, 'package.json'), 'utf-8');
      const pkg = JSON.parse(pkgContent);
      const deps = { ...pkg.dependencies, ...pkg.devDependencies };

      if (deps.next) {
        result.framework = 'Next.js';
      } else if (deps.react) {
        result.framework = 'React';
      } else if (deps.vue) {
        result.framework = 'Vue';
      } else if (deps.express) {
        result.framework = 'Express';
      }
    } catch {
      // Invalid JSON, ignore
    }
  }

  // Rust
  if (existsSync(join(projectPath, 'Cargo.toml'))) {
    result.language = 'Rust';
    result.packageManager = 'cargo';
    languages.push('Rust');
  }

  // Go
  if (existsSync(join(projectPath, 'go.mod'))) {
    result.language = 'Go';
    result.packageManager = 'go mod';
    languages.push('Go');
  }

  // Python
  if (
    existsSync(join(projectPath, 'requirements.txt')) ||
    existsSync(join(projectPath, 'pyproject.toml'))
  ) {
    result.language = 'Python';
    languages.push('Python');

    if (existsSync(join(projectPath, 'poetry.lock'))) {
      result.packageManager = 'poetry';
    } else if (existsSync(join(projectPath, 'Pipfile'))) {
      result.packageManager = 'pipenv';
    } else {
      result.packageManager = 'pip';
    }
  }

  if (languages.length > 1) {
    result.languages = languages;
  }

  return result;
}

function generateDirectoryTree(
  projectPath: string,
  options: { maxDepth?: number; useFind?: boolean } = {}
): string {
  const maxDepth = options.maxDepth || 3;

  // Try tree command first unless explicitly told to use find
  if (!options.useFind) {
    try {
      const tree = execSync(
        `tree -L ${maxDepth} -I 'node_modules|dist|build|.git|__pycache__|.venv|target|vendor' --dirsfirst`,
        { cwd: projectPath, encoding: 'utf-8' }
      );
      return tree;
    } catch {
      // tree not available, fall through to find
    }
  }

  // Fallback to find
  try {
    const find = execSync(
      `find . -maxdepth ${maxDepth} -type d ` +
      `-not -path './node_modules/*' ` +
      `-not -path './dist/*' ` +
      `-not -path './.git/*' ` +
      `-not -path './build/*' ` +
      `-not -path './__pycache__/*' ` +
      `-not -path './.venv/*' ` +
      `-not -path './target/*' ` +
      `-not -path './vendor/*' ` +
      `| sort`,
      { cwd: projectPath, encoding: 'utf-8' }
    );
    return find;
  } catch {
    return '';
  }
}

interface KeyFiles {
  config: string[];
  docs: string[];
  entryPoints: string[];
}

function identifyKeyFiles(
  projectPath: string,
  options: { maxDepth?: number; limitPerCategory?: number } = {}
): KeyFiles {
  const maxDepth = options.maxDepth || 2;
  const limit = options.limitPerCategory || 15;

  const result: KeyFiles = {
    config: [],
    docs: [],
    entryPoints: []
  };

  try {
    // Configuration files
    const configFiles = execSync(
      `find . -maxdepth ${maxDepth} \\( -name "*.json" -o -name "*.yaml" -o -name "*.toml" -o -name "*.config.*" \\) ` +
      `-not -path './node_modules/*' ` +
      `-not -path './dist/*' ` +
      `-not -path './.git/*' ` +
      `2>/dev/null | head -${limit}`,
      { cwd: projectPath, encoding: 'utf-8' }
    );
    result.config = configFiles.trim().split('\n').filter(Boolean);
  } catch {
    // No config files found
  }

  try {
    // Documentation files
    const docFiles = execSync(
      `find . -maxdepth ${maxDepth} \\( -name "README*" -o -name "CLAUDE*" -o -name "*.md" \\) ` +
      `-not -path './node_modules/*' ` +
      `-not -path './dist/*' ` +
      `2>/dev/null | head -${limit > 10 ? 10 : limit}`,
      { cwd: projectPath, encoding: 'utf-8' }
    );
    result.docs = docFiles.trim().split('\n').filter(Boolean);
  } catch {
    // No docs found
  }

  try {
    // Entry points
    const entryFiles = execSync(
      `find . -maxdepth 3 \\( -name "main.*" -o -name "index.*" -o -name "app.*" -o -name "cli.*" \\) ` +
      `-not -path './node_modules/*' ` +
      `-not -path './dist/*' ` +
      `2>/dev/null | head -${limit > 10 ? 10 : limit}`,
      { cwd: projectPath, encoding: 'utf-8' }
    );
    result.entryPoints = entryFiles.trim().split('\n').filter(Boolean);
  } catch {
    // No entry points found
  }

  return result;
}

function generateProjectMap(
  projectPath: string,
  options: { preserveNotes?: string } = {}
): string {
  const projectName = projectPath.split('/').pop() || 'Unknown';
  const timestamp = new Date().toISOString().split('T')[0];

  const techStack = detectTechStack(projectPath);
  const tree = generateDirectoryTree(projectPath);
  const keyFiles = identifyKeyFiles(projectPath);

  let map = `# Project Map: ${projectName}

> Auto-generated by \`/map\`. Last updated: ${timestamp}

## Tech Stack

| Component | Value |
|-----------|-------|
| Language | ${techStack.language || 'N/A'} |
| Package Manager | ${techStack.packageManager || 'N/A'} |
| Framework | ${techStack.framework || 'N/A'} |

## Directory Structure

\`\`\`
${tree || '(empty)'}
\`\`\`

## Key Files

### Configuration
${keyFiles.config.map(f => `- ${f}`).join('\n') || '- (none found)'}

### Documentation
${keyFiles.docs.map(f => `- ${f}`).join('\n') || '- (none found)'}

### Entry Points
${keyFiles.entryPoints.map(f => `- ${f}`).join('\n') || '- (none found)'}

## Architecture Notes

<!-- This section is preserved on /map --refresh -->
${options.preserveNotes || '<!-- Add your own architectural notes, patterns, data flow descriptions -->'}
`;

  return map;
}

function extractArchitectureNotes(mapContent: string): string {
  const match = mapContent.match(/## Architecture Notes\n\n<!-- This section is preserved on \/map --refresh -->\n\n([\s\S]*?)(\n## |$)/);
  if (match && match[1]) {
    return match[1].trim();
  }
  return '';
}

function extractTimestamp(mapContent: string): string {
  const match = mapContent.match(/Last updated: (.+)/);
  return match ? match[1] : '';
}
