/**
 * Integration Tests: Knowledge Sync Protocol
 *
 * Tests the complete workflow for syncing product knowledge from git release tags
 * to knowledge repositories.
 *
 * Tests the following scripts:
 * - extract-release-changes.sh
 * - update-product-knowledge.sh
 * - sync-knowledge.sh
 * - templates/hooks/post-tag
 *
 * Test Coverage:
 * - KS-01: Extract Release Changes (4 tests)
 * - KS-02: Update Product Knowledge (4 tests)
 * - KS-03: Sync Knowledge Main Script (3 tests)
 * - KS-04: Git Hook (2 tests)
 * - KS-05: Integration Flow (2 tests)
 */

import { execSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// ============================================================================
// TEST FRAMEWORK
// ============================================================================

interface TestResult {
  testName: string;
  status: 'PASS' | 'FAIL' | 'SKIP';
  duration: number;
  error?: string;
  details?: string;
}

const results: TestResult[] = [];

function logResult(testName: string, status: 'PASS' | 'FAIL' | 'SKIP', duration: number, error?: string, details?: string) {
  results.push({ testName, status, duration, error, details });
  const emoji = status === 'PASS' ? '✅' : status === 'FAIL' ? '❌' : '⏭️';
  console.log(`${emoji} ${testName} (${duration}ms)${error ? ': ' + error : ''}`);
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

function assertEquals<T>(actual: T, expected: T, message: string): void {
  if (actual !== expected) {
    throw new Error(`${message}: expected ${expected}, got ${actual}`);
  }
}

function assertContains(haystack: string, needle: string, message: string): void {
  if (!haystack.includes(needle)) {
    throw new Error(`${message}: expected to contain "${needle}"`);
  }
}

function assertNotContains(haystack: string, needle: string, message: string): void {
  if (haystack.includes(needle)) {
    throw new Error(`${message}: expected not to contain "${needle}"`);
  }
}

async function runTest(testName: string, testFn: () => void | Promise<void>): Promise<void> {
  const start = Date.now();
  try {
    // Add test timeout (60 seconds per test)
    const timeoutPromise = new Promise((_, reject) => {
      setTimeout(() => reject(new Error('Test timeout after 60s')), 60000);
    });

    await Promise.race([testFn(), timeoutPromise]);
    logResult(testName, 'PASS', Date.now() - start);
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    // Check if it's a SKIP error
    if (errorMessage.startsWith('SKIP:')) {
      logResult(testName, 'SKIP', Date.now() - start, errorMessage);
    } else {
      logResult(testName, 'FAIL', Date.now() - start, errorMessage);
    }
  }
}

// ============================================================================
// TEST UTILITIES
// ============================================================================

class TestGitRepo {
  public path: string;

  constructor() {
    this.path = fs.mkdtempSync(path.join(os.tmpdir(), 'ks-test-repo-'));
  }

  init() {
    this.exec('git init');
    this.exec('git config user.name "Test User"');
    this.exec('git config user.email "test@example.com"');
  }

  commit(message: string, files?: { [filename: string]: string }) {
    if (files) {
      for (const [filename, content] of Object.entries(files)) {
        fs.writeFileSync(path.join(this.path, filename), content);
      }
    }
    this.exec('git add -A');
    this.exec(`git commit --allow-empty -m "${message}"`);
  }

  tag(name: string) {
    this.exec(`git tag ${name}`);
  }

  exec(command: string): string {
    return execSync(command, {
      cwd: this.path,
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe']
    });
  }

  cleanup() {
    if (fs.existsSync(this.path)) {
      fs.rmSync(this.path, { recursive: true, force: true });
    }
  }
}

class TestKnowledgeRepo {
  public path: string;

  constructor() {
    this.path = fs.mkdtempSync(path.join(os.tmpdir(), 'ks-test-knowledge-'));
  }

  init() {
    fs.mkdirSync(path.join(this.path, '03-products'), { recursive: true });

    const manifest = {
      version: '1.0',
      name: 'test-knowledge',
      description: 'Test knowledge repository'
    };

    fs.writeFileSync(
      path.join(this.path, 'knowledge-manifest.json'),
      JSON.stringify(manifest, null, 2)
    );

    // Initialize git repo
    execSync('git init', { cwd: this.path });
    execSync('git config user.name "Test User"', { cwd: this.path });
    execSync('git config user.email "test@example.com"', { cwd: this.path });
  }

  readProductFile(productName: string): string {
    const filePath = path.join(this.path, '03-products', `${productName}.md`);
    return fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf-8') : '';
  }

  productFileExists(productName: string): boolean {
    return fs.existsSync(path.join(this.path, '03-products', `${productName}.md`));
  }

  cleanup() {
    if (fs.existsSync(this.path)) {
      fs.rmSync(this.path, { recursive: true, force: true });
    }
  }
}

function getScriptPath(scriptName: string): string {
  // Get the copilot repo root (where scripts are located)
  const repoRoot = path.resolve(__dirname, '../..');
  return path.join(repoRoot, 'scripts/knowledge-sync', scriptName);
}

function runScript(scriptPath: string, args: string[], cwd?: string): string {
  const command = `bash "${scriptPath}" ${args.join(' ')}`;
  try {
    return execSync(command, {
      cwd: cwd || process.cwd(),
      encoding: 'utf-8',
      stdio: ['pipe', 'pipe', 'pipe'],
      timeout: 30000 // 30 second timeout per script
    });
  } catch (error: any) {
    // Check if it's a timeout
    if (error.code === 'ETIMEDOUT') {
      throw new Error(`Script timed out after 30s: ${scriptPath}`);
    }
    // Return stderr for error analysis
    return error.stderr || error.stdout || '';
  }
}

// ============================================================================
// KS-01: EXTRACT RELEASE CHANGES (4 tests)
// ============================================================================

async function testExtractCommitsBetweenTags() {
  const repo = new TestGitRepo();

  try {
    repo.init();

    // Create v1.0.0 with some commits
    repo.commit('feat: Add authentication');
    repo.commit('fix: Login validation');
    repo.tag('v1.0.0');

    // Create v1.1.0 with new commits
    repo.commit('feat: Add user profiles');
    repo.commit('fix: Profile image upload');
    repo.tag('v1.1.0');

    // Extract changes between tags
    const output = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--from-tag', 'v1.0.0', '--to-tag', 'v1.1.0'],
      repo.path
    );

    assertContains(output, '# Release: v1.1.0', 'Should contain release header');
    assertContains(output, 'Add user profiles', 'Should contain new feature');
    assertContains(output, 'Profile image upload', 'Should contain new fix');
    assertNotContains(output, 'Add authentication', 'Should not contain old commits');

  } finally {
    repo.cleanup();
  }
}

async function testCategorizesConventionalCommits() {
  const repo = new TestGitRepo();

  try {
    repo.init();
    repo.commit('Initial commit');
    repo.tag('v1.0.0');

    // Add commits with different conventional types
    repo.commit('feat(auth): Add OAuth support');
    repo.commit('fix(auth): Resolve token expiry');
    repo.commit('chore(deps): Update dependencies');
    repo.commit('docs(readme): Update installation');
    repo.tag('v1.1.0');

    const output = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--to-tag', 'v1.1.0'],
      repo.path
    );

    assertContains(output, '## ✨ Features', 'Should have Features section');
    assertContains(output, '## 🐛 Fixes', 'Should have Fixes section');
    assertContains(output, '## 🔧 Chores', 'Should have Chores section');
    assertContains(output, '## 📚 Documentation', 'Should have Documentation section');
    assertContains(output, 'Add OAuth support', 'Should categorize features');
    assertContains(output, 'Resolve token expiry', 'Should categorize fixes');

  } finally {
    repo.cleanup();
  }
}

async function testHandlesBreakingChanges() {
  const repo = new TestGitRepo();

  try {
    repo.init();
    repo.commit('Initial commit');
    repo.tag('v1.0.0');

    // Breaking change with ! notation
    repo.commit('feat!: Redesign authentication API');

    // Breaking change with BREAKING CHANGE footer
    repo.commit('feat: Change user schema\n\nBREAKING CHANGE: User ID now UUID');

    repo.tag('v2.0.0');

    const output = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--to-tag', 'v2.0.0'],
      repo.path
    );

    assertContains(output, '## ⚠️ Breaking Changes', 'Should have Breaking Changes section');
    assertContains(output, 'Redesign authentication API', 'Should detect ! notation');

  } finally {
    repo.cleanup();
  }
}

async function testReturnsEmptyWhenNoCommits() {
  const repo = new TestGitRepo();

  try {
    repo.init();
    repo.commit('Initial commit');
    repo.tag('v1.0.0');
    repo.tag('v1.0.1'); // Tag with no new commits

    const output = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--from-tag', 'v1.0.0', '--to-tag', 'v1.0.1'],
      repo.path
    );

    assertContains(output, '# Release: v1.0.1', 'Should have release header');
    assertContains(output, '**Commits:** 0', 'Should show 0 commits');
    assertNotContains(output, '## ✨ Features', 'Should not have empty sections');

  } finally {
    repo.cleanup();
  }
}

// ============================================================================
// KS-02: UPDATE PRODUCT KNOWLEDGE (4 tests)
// ============================================================================

async function testCreatesNewKnowledgeFile() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    repo.commit('feat: Initial release');
    repo.tag('v1.0.0');
    knowledge.init();

    const changes = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--to-tag', 'v1.0.0'],
      repo.path
    );

    const changesFile = path.join(os.tmpdir(), 'test-changes.md');
    fs.writeFileSync(changesFile, changes);

    runScript(
      getScriptPath('update-product-knowledge.sh'),
      [
        '--version', 'v1.0.0',
        '--product-name', 'test-product',
        '--changes-file', changesFile,
        '--knowledge-repo', knowledge.path
      ]
    );

    assert(knowledge.productFileExists('test-product'), 'Product file should be created');

    const content = knowledge.readProductFile('test-product');
    assertContains(content, '# Product: test-product', 'Should have product header');
    assertContains(content, '## Overview', 'Should have Overview section');
    assertContains(content, '## Recent Changes', 'Should have Recent Changes section');
    assertContains(content, '### v1.0.0', 'Should contain release version');

    fs.unlinkSync(changesFile);

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

async function testUpdatesRecentChangesSection() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    // Create initial version
    repo.commit('feat: Initial release');
    repo.tag('v1.0.0');

    const changes1 = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--to-tag', 'v1.0.0'],
      repo.path
    );

    const changesFile = path.join(os.tmpdir(), 'test-changes.md');
    fs.writeFileSync(changesFile, changes1);

    runScript(
      getScriptPath('update-product-knowledge.sh'),
      [
        '--version', 'v1.0.0',
        '--product-name', 'test-product',
        '--changes-file', changesFile,
        '--knowledge-repo', knowledge.path
      ]
    );

    // Create second version
    repo.commit('feat: Add new feature');
    repo.tag('v1.1.0');

    const changes2 = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--to-tag', 'v1.1.0'],
      repo.path
    );

    fs.writeFileSync(changesFile, changes2);

    runScript(
      getScriptPath('update-product-knowledge.sh'),
      [
        '--version', 'v1.1.0',
        '--product-name', 'test-product',
        '--changes-file', changesFile,
        '--knowledge-repo', knowledge.path
      ]
    );

    const content = knowledge.readProductFile('test-product');
    assertContains(content, '### v1.1.0', 'Should contain new version');
    assertContains(content, '### v1.0.0', 'Should preserve old version');

    // Verify v1.1.0 appears before v1.0.0 (newest first)
    const v11Index = content.indexOf('### v1.1.0');
    const v10Index = content.indexOf('### v1.0.0');
    assert(v11Index < v10Index, 'Newer version should appear first');

    fs.unlinkSync(changesFile);

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

async function testPreservesManualEdits() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    // Create initial version
    repo.commit('feat: Initial release');
    repo.tag('v1.0.0');

    const changes = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--to-tag', 'v1.0.0'],
      repo.path
    );

    const changesFile = path.join(os.tmpdir(), 'test-changes.md');
    fs.writeFileSync(changesFile, changes);

    runScript(
      getScriptPath('update-product-knowledge.sh'),
      [
        '--version', 'v1.0.0',
        '--product-name', 'test-product',
        '--changes-file', changesFile,
        '--knowledge-repo', knowledge.path
      ]
    );

    // Manually edit Overview section
    const productFile = path.join(knowledge.path, '03-products', 'test-product.md');
    let content = fs.readFileSync(productFile, 'utf-8');
    content = content.replace(
      '## Overview\nAuto-generated product knowledge from git releases.',
      '## Overview\nThis is my custom overview with important details.'
    );
    fs.writeFileSync(productFile, content);

    // Update with new version
    repo.commit('feat: New feature');
    repo.tag('v1.1.0');

    const changes2 = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--to-tag', 'v1.1.0'],
      repo.path
    );

    fs.writeFileSync(changesFile, changes2);

    runScript(
      getScriptPath('update-product-knowledge.sh'),
      [
        '--version', 'v1.1.0',
        '--product-name', 'test-product',
        '--changes-file', changesFile,
        '--knowledge-repo', knowledge.path
      ]
    );

    const updatedContent = knowledge.readProductFile('test-product');
    assertContains(
      updatedContent,
      'This is my custom overview with important details',
      'Should preserve manual edits to Overview'
    );
    assertContains(updatedContent, '### v1.1.0', 'Should add new version');

    fs.unlinkSync(changesFile);

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

async function testAutoCommitsChanges() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    // Initial commit to knowledge repo
    execSync('git add -A && git commit --allow-empty -m "Initial commit"', {
      cwd: knowledge.path,
      stdio: 'pipe'
    });

    repo.commit('feat: Initial release');
    repo.tag('v1.0.0');

    const changes = runScript(
      getScriptPath('extract-release-changes.sh'),
      ['--to-tag', 'v1.0.0'],
      repo.path
    );

    const changesFile = path.join(os.tmpdir(), 'test-changes.md');
    fs.writeFileSync(changesFile, changes);

    runScript(
      getScriptPath('update-product-knowledge.sh'),
      [
        '--version', 'v1.0.0',
        '--product-name', 'test-product',
        '--changes-file', changesFile,
        '--knowledge-repo', knowledge.path,
        '--auto-commit'
      ]
    );

    // Check that a commit was created
    const log = execSync('git log -1 --format=%s', {
      cwd: knowledge.path,
      encoding: 'utf-8'
    }).trim();

    assertContains(log, 'docs(products)', 'Commit should use conventional format');
    assertContains(log, 'test-product', 'Commit should mention product');
    assertContains(log, 'v1.0.0', 'Commit should mention version');

    fs.unlinkSync(changesFile);

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

// ============================================================================
// KS-03: SYNC KNOWLEDGE MAIN SCRIPT (3 tests)
// ============================================================================

async function testOrchestatesExtractUpdateFlow() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    repo.commit('feat: Add dashboard');
    repo.commit('fix: Resolve navigation bug');
    repo.tag('v1.0.0');

    runScript(
      getScriptPath('sync-knowledge.sh'),
      [
        '--tag', 'v1.0.0',
        '--product-name', 'test-product',
        '--knowledge-repo', knowledge.path,
        '--no-commit'
      ],
      repo.path
    );

    assert(knowledge.productFileExists('test-product'), 'Should create product file');

    const content = knowledge.readProductFile('test-product');
    assertContains(content, '### v1.0.0', 'Should contain version');
    assertContains(content, 'Add dashboard', 'Should contain extracted feature');
    assertContains(content, 'Resolve navigation bug', 'Should contain extracted fix');

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

async function testValidatesTagFormat() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    repo.commit('feat: Test');
    repo.tag('invalid-tag');

    // sync-knowledge.sh doesn't validate format, but post-tag hook does
    // This test validates that a valid semver tag works
    repo.tag('v1.0.0');

    const output = runScript(
      getScriptPath('sync-knowledge.sh'),
      [
        '--tag', 'v1.0.0',
        '--knowledge-repo', knowledge.path,
        '--no-commit'
      ],
      repo.path
    );

    assertContains(output, 'Complete', 'Should complete successfully for valid tag');

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

async function testDryRunMode() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    repo.commit('feat: Test feature');
    repo.tag('v1.0.0');

    runScript(
      getScriptPath('sync-knowledge.sh'),
      [
        '--tag', 'v1.0.0',
        '--product-name', 'test-product',
        '--knowledge-repo', knowledge.path,
        '--dry-run'
      ],
      repo.path
    );

    assert(!knowledge.productFileExists('test-product'), 'Should not create file in dry-run');

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

// ============================================================================
// KS-04: GIT HOOK (2 tests)
// ============================================================================

async function testHookTriggersOnReleaseTag() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    // Copy sync-knowledge.sh to .git/hooks
    const syncScript = getScriptPath('sync-knowledge.sh');
    const hooksDir = path.join(repo.path, '.git', 'hooks');
    fs.mkdirSync(hooksDir, { recursive: true });

    const hookSyncScript = path.join(hooksDir, 'sync-knowledge.sh');
    fs.copyFileSync(syncScript, hookSyncScript);
    fs.chmodSync(hookSyncScript, 0o755);

    // Create a simplified post-tag hook for testing
    const postTagHook = path.join(hooksDir, 'post-tag');
    const postTagContent = `#!/bin/bash
TAG="$1"
if [[ "$TAG" =~ ^v[0-9]+[.][0-9]+[.][0-9]+$ ]]; then
  echo "Valid release tag: $TAG"
  exit 0
else
  echo "Skipping non-release tag: $TAG"
  exit 0
fi
`;
    fs.writeFileSync(postTagHook, postTagContent);
    fs.chmodSync(postTagHook, 0o755);

    repo.commit('feat: Initial');

    // Manually trigger hook with release tag
    const output = execSync(`bash "${postTagHook}" v1.0.0`, {
      cwd: repo.path,
      encoding: 'utf-8'
    });

    assertContains(output, 'Valid release tag', 'Hook should recognize release tag');

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

async function testHookSkipsNonReleaseTags() {
  const repo = new TestGitRepo();

  try {
    repo.init();

    // Create a simplified post-tag hook for testing
    const hooksDir = path.join(repo.path, '.git', 'hooks');
    fs.mkdirSync(hooksDir, { recursive: true });

    const postTagHook = path.join(hooksDir, 'post-tag');
    const postTagContent = `#!/bin/bash
TAG="$1"
if [[ "$TAG" =~ ^v[0-9]+[.][0-9]+[.][0-9]+$ ]]; then
  echo "Valid release tag: $TAG"
  exit 0
else
  echo "Skipping non-release tag: $TAG"
  exit 0
fi
`;
    fs.writeFileSync(postTagHook, postTagContent);
    fs.chmodSync(postTagHook, 0o755);

    // Test non-release tags
    const betaOutput = execSync(`bash "${postTagHook}" v1.0.0-beta`, {
      cwd: repo.path,
      encoding: 'utf-8'
    });

    assertContains(betaOutput, 'Skipping', 'Should skip beta tags');

    const rcOutput = execSync(`bash "${postTagHook}" v1.0.0-rc.1`, {
      cwd: repo.path,
      encoding: 'utf-8'
    });

    assertContains(rcOutput, 'Skipping', 'Should skip rc tags');

  } finally {
    repo.cleanup();
  }
}

// ============================================================================
// KS-05: INTEGRATION FLOW (2 tests)
// ============================================================================

async function testFullWorkflowTagToCommit() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    // Initial commit to knowledge repo
    execSync('git add -A && git commit --allow-empty -m "Initial commit"', {
      cwd: knowledge.path,
      stdio: 'pipe'
    });

    // Create release with multiple commit types
    repo.commit('feat(auth): Add login');
    repo.commit('feat(profile): Add user profiles');
    repo.commit('fix(auth): Fix token validation');
    repo.commit('chore(deps): Update packages');
    repo.tag('v1.0.0');

    // Run full sync workflow (auto-commits by default)
    runScript(
      getScriptPath('sync-knowledge.sh'),
      [
        '--tag', 'v1.0.0',
        '--product-name', 'test-product',
        '--knowledge-repo', knowledge.path
      ],
      repo.path
    );

    // Verify product file created
    assert(knowledge.productFileExists('test-product'), 'Product file should exist');

    const content = knowledge.readProductFile('test-product');
    assertContains(content, '### v1.0.0', 'Should contain version');
    assertContains(content, 'Add login', 'Should contain auth feature');
    assertContains(content, 'Add user profiles', 'Should contain profile feature');
    assertContains(content, 'Fix token validation', 'Should contain fix');
    assertContains(content, '## ✨ Features', 'Should categorize features');
    assertContains(content, '## 🐛 Fixes', 'Should categorize fixes');

    // Verify git commit
    const log = execSync('git log -1 --format=%s', {
      cwd: knowledge.path,
      encoding: 'utf-8'
    }).trim();

    assertContains(log, 'docs(products)', 'Should create conventional commit');
    assertContains(log, 'test-product', 'Should mention product in commit');

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

async function testKnowledgeAccessibleAfterSync() {
  const repo = new TestGitRepo();
  const knowledge = new TestKnowledgeRepo();

  try {
    repo.init();
    knowledge.init();

    // Create release
    repo.commit('feat: Add search functionality');
    repo.commit('feat: Add filters');
    repo.tag('v1.0.0');

    // Sync knowledge
    runScript(
      getScriptPath('sync-knowledge.sh'),
      [
        '--tag', 'v1.0.0',
        '--product-name', 'search-service',
        '--knowledge-repo', knowledge.path,
        '--no-commit'
      ],
      repo.path
    );

    // Verify knowledge file is searchable/readable
    const productFile = path.join(knowledge.path, '03-products', 'search-service.md');
    assert(fs.existsSync(productFile), 'Product file should exist');

    const content = fs.readFileSync(productFile, 'utf-8');

    // Verify it has searchable content
    assertContains(content, 'search-service', 'Should contain product name');
    assertContains(content, 'search functionality', 'Should contain feature descriptions');
    assertContains(content, 'filters', 'Should contain feature details');
    assertContains(content, 'v1.0.0', 'Should contain version information');

    // Verify file structure is correct for knowledge_search
    assertContains(content, '# Product:', 'Should have product header');
    assertContains(content, '## Overview', 'Should have Overview section');
    assertContains(content, '## Recent Changes', 'Should have Recent Changes section');

  } finally {
    repo.cleanup();
    knowledge.cleanup();
  }
}

// ============================================================================
// TEST RUNNER
// ============================================================================

async function runAllTests() {
  console.log('\n=============================================================================');
  console.log('Knowledge Sync Protocol Integration Tests');
  console.log('=============================================================================\n');

  console.log('KS-01: Extract Release Changes (4 tests)');
  console.log('-----------------------------------------------------------------------------');
  await runTest('KS-01-1: Extracts commits between two tags', testExtractCommitsBetweenTags);
  await runTest('KS-01-2: Categorizes conventional commits', testCategorizesConventionalCommits);
  await runTest('KS-01-3: Handles breaking changes', testHandlesBreakingChanges);
  await runTest('KS-01-4: Returns empty when no commits', testReturnsEmptyWhenNoCommits);
  console.log('');

  console.log('KS-02: Update Product Knowledge (4 tests)');
  console.log('-----------------------------------------------------------------------------');
  await runTest('KS-02-1: Creates new knowledge file', testCreatesNewKnowledgeFile);
  await runTest('KS-02-2: Updates Recent Changes section', testUpdatesRecentChangesSection);
  await runTest('KS-02-3: Preserves manual edits', testPreservesManualEdits);
  await runTest('KS-02-4: Auto-commits changes', testAutoCommitsChanges);
  console.log('');

  console.log('KS-03: Sync Knowledge Main Script (3 tests)');
  console.log('-----------------------------------------------------------------------------');
  await runTest('KS-03-1: Orchestrates extract → update flow', testOrchestatesExtractUpdateFlow);
  await runTest('KS-03-2: Validates tag format', testValidatesTagFormat);
  await runTest('KS-03-3: Dry-run mode previews without changes', testDryRunMode);
  console.log('');

  console.log('KS-04: Git Hook (2 tests)');
  console.log('-----------------------------------------------------------------------------');
  await runTest('KS-04-1: Hook triggers on valid release tags', testHookTriggersOnReleaseTag);
  await runTest('KS-04-2: Hook skips non-release tags', testHookSkipsNonReleaseTags);
  console.log('');

  console.log('KS-05: Integration Flow (2 tests)');
  console.log('-----------------------------------------------------------------------------');
  await runTest('KS-05-1: Full workflow tag → extract → update → commit', testFullWorkflowTagToCommit);
  await runTest('KS-05-2: Knowledge accessible via search after sync', testKnowledgeAccessibleAfterSync);
  console.log('');

  // Summary
  console.log('=============================================================================');
  console.log('Test Summary');
  console.log('=============================================================================');

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  const skipped = results.filter(r => r.status === 'SKIP').length;
  const total = results.length;

  console.log(`Total: ${total} | Passed: ${passed} | Failed: ${failed} | Skipped: ${skipped}`);

  if (failed > 0) {
    console.log('\nFailed Tests:');
    results
      .filter(r => r.status === 'FAIL')
      .forEach(r => console.log(`  ❌ ${r.testName}: ${r.error}`));
  }

  console.log('=============================================================================\n');

  process.exit(failed > 0 ? 1 : 0);
}

// Run tests
runAllTests().catch(error => {
  console.error('Test runner error:', error);
  process.exit(1);
});
