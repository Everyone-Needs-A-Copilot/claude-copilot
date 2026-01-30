/**
 * Integration Tests: OMC Features
 *
 * Tests the 5 features from OMC Learnings Integration:
 * 1. Ecomode - Model routing based on complexity
 * 2. Magic Keywords - Action and modifier keyword parsing
 * 3. Progress HUD - Statusline rendering
 * 4. Skill Extraction - Pattern detection
 * 5. Zero-Config Install - Dependency checking
 *
 * @see PRD-omc-learnings
 */

import { readFileSync, existsSync } from 'fs';
import { join } from 'path';

// Import feature implementations
import { routeToModel, detectModifierKeyword, stripModifierKeywords } from '../../mcp-servers/task-copilot/src/ecomode/model-router.js';
import { parseKeywords, hasKeywords, validateKeywords } from '../../.claude/commands/keyword-parser.js';
import { renderStatusline, createStatusline, calculateProgress } from '../../mcp-servers/task-copilot/src/hud/statusline.js';

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

function runTest(testName: string, testFn: () => void | Promise<void>): void {
  const start = Date.now();

  Promise.resolve()
    .then(() => testFn())
    .then(() => {
      const duration = Date.now() - start;
      logResult(testName, 'PASS', duration);
    })
    .catch((error) => {
      const duration = Date.now() - start;
      logResult(testName, 'FAIL', duration, error.message);
    });
}

// ============================================================================
// FEATURE 1: ECOMODE - MODEL ROUTING
// ============================================================================

runTest('Ecomode: Routes simple task to haiku', () => {
  const result = routeToModel({
    title: 'Fix typo in README',
    fileCount: 1,
    agentId: 'me'
  });

  assertEquals(result.route.model, 'haiku', 'Simple task should route to haiku');
  assert(result.complexityScore.score < 0.3, 'Complexity score should be low');
});

runTest('Ecomode: Routes complex task to opus', () => {
  const result = routeToModel({
    title: 'Design microservices architecture with event sourcing',
    description: 'Implement CQRS pattern across multiple services',
    fileCount: 15,
    agentId: 'ta'
  });

  assertEquals(result.route.model, 'opus', 'Complex task should route to opus');
  assert(result.complexityScore.score > 0.7, 'Complexity score should be high');
});

runTest('Ecomode: Routes medium complexity task to sonnet', () => {
  const result = routeToModel({
    title: 'Add authentication middleware',
    description: 'JWT validation and user session management',
    fileCount: 3,
    agentId: 'me'
  });

  assertEquals(result.route.model, 'sonnet', 'Medium task should route to sonnet');
  assert(result.complexityScore.score >= 0.3 && result.complexityScore.score < 0.7,
    'Complexity score should be medium');
});

runTest('Ecomode: Detects eco: modifier', () => {
  const modifier = detectModifierKeyword('eco: Fix the login bug');

  assert(modifier !== null, 'Should detect eco: modifier');
  assertEquals(modifier!.keyword, 'eco', 'Should extract eco keyword');
  assertEquals(modifier!.targetModel, null, 'eco: should not force specific model');
});

runTest('Ecomode: Detects opus: override', () => {
  const modifier = detectModifierKeyword('opus: Design system architecture');

  assert(modifier !== null, 'Should detect opus: modifier');
  assertEquals(modifier!.keyword, 'opus', 'Should extract opus keyword');
  assertEquals(modifier!.targetModel, 'opus', 'opus: should force opus model');
});

runTest('Ecomode: Detects fast: override', () => {
  const modifier = detectModifierKeyword('fast: Fix typo');

  assert(modifier !== null, 'Should detect fast: modifier');
  assertEquals(modifier!.keyword, 'fast', 'Should extract fast keyword');
  assertEquals(modifier!.targetModel, 'haiku', 'fast: should force haiku model');
});

runTest('Ecomode: Overrides complexity with opus:', () => {
  const result = routeToModel({
    title: 'opus: Fix simple typo',
    fileCount: 1,
    agentId: 'me'
  });

  assertEquals(result.route.model, 'opus', 'opus: should override low complexity');
  assert(result.route.isOverride, 'Should be marked as override');
});

runTest('Ecomode: Strips modifier keywords from text', () => {
  const stripped = stripModifierKeywords('eco: Fix the login bug');
  assertEquals(stripped, 'Fix the login bug', 'Should strip eco: prefix');

  const stripped2 = stripModifierKeywords('opus: Design architecture');
  assertEquals(stripped2, 'Design architecture', 'Should strip opus: prefix');
});

// ============================================================================
// FEATURE 2: MAGIC KEYWORDS
// ============================================================================

runTest('Magic Keywords: Parses eco: modifier', () => {
  const parsed = parseKeywords('eco: fix: the login bug');

  assert(parsed.valid, 'Should be valid');
  assert(parsed.modifier !== null, 'Should detect modifier');
  assertEquals(parsed.modifier!.keyword, 'eco', 'Should extract eco');
  assert(parsed.action !== null, 'Should detect action');
  assertEquals(parsed.action!.keyword, 'fix', 'Should extract fix');
  assertEquals(parsed.cleanMessage, 'the login bug', 'Should clean message');
});

runTest('Magic Keywords: Parses opus: add: combination', () => {
  const parsed = parseKeywords('opus: add: dark mode feature');

  assert(parsed.valid, 'Should be valid');
  assertEquals(parsed.modifier!.keyword, 'opus', 'Should extract opus');
  assertEquals(parsed.action!.keyword, 'add', 'Should extract add');
  assertEquals(parsed.cleanMessage, 'dark mode feature', 'Should clean message');
});

runTest('Magic Keywords: Handles action without modifier', () => {
  const parsed = parseKeywords('fix: authentication error');

  assert(parsed.valid, 'Should be valid');
  assert(parsed.modifier === null, 'Should not detect modifier');
  assert(parsed.action !== null, 'Should detect action');
  assertEquals(parsed.action!.keyword, 'fix', 'Should extract fix');
  assertEquals(parsed.cleanMessage, 'authentication error', 'Should clean message');
});

runTest('Magic Keywords: Handles modifier without action', () => {
  const parsed = parseKeywords('fast: update the config');

  assert(parsed.valid, 'Should be valid');
  assert(parsed.modifier !== null, 'Should detect modifier');
  assertEquals(parsed.modifier!.keyword, 'fast', 'Should extract fast');
  assert(parsed.action === null, 'Should not detect action');
  assertEquals(parsed.cleanMessage, 'update the config', 'Should clean message');
});

runTest('Magic Keywords: Ignores false positives', () => {
  const parsed = parseKeywords('economics: is a complex topic');

  assert(parsed.valid, 'Should be valid');
  assert(parsed.modifier === null, 'Should not detect eco in economics');
  assertEquals(parsed.cleanMessage, 'economics: is a complex topic', 'Should preserve original');
});

runTest('Magic Keywords: Detects all action keywords', () => {
  const actions = ['fix:', 'add:', 'refactor:', 'optimize:', 'test:', 'doc:', 'deploy:'];

  for (const action of actions) {
    const parsed = parseKeywords(`${action} something`);
    assert(parsed.action !== null, `Should detect ${action}`);
  }
});

runTest('Magic Keywords: Validates keywords', () => {
  const valid = validateKeywords('eco: fix: the bug');
  assertEquals(valid.length, 0, 'Should have no errors');

  const valid2 = validateKeywords('fix: authentication');
  assertEquals(valid2.length, 0, 'Should have no errors');
});

runTest('Magic Keywords: hasKeywords detection', () => {
  assert(hasKeywords('eco: fix: bug'), 'Should detect keywords');
  assert(hasKeywords('fix: bug'), 'Should detect keywords');
  assert(hasKeywords('opus: add feature'), 'Should detect keywords');
  assert(!hasKeywords('just a normal message'), 'Should not detect keywords');
  assert(!hasKeywords('economics: is complex'), 'Should not detect false positives');
});

// ============================================================================
// FEATURE 3: PROGRESS HUD - STATUSLINE
// ============================================================================

runTest('Progress HUD: Renders basic statusline', () => {
  const state = {
    taskId: 'TASK-123',
    taskTitle: 'Fix login bug',
    status: 'in_progress' as const,
    progressPercent: 50,
    streamId: 'Stream-A',
    activeFiles: ['src/auth/login.ts'],
    lastUpdate: new Date().toISOString()
  };

  const rendered = renderStatusline(state, 'sonnet', 1200);

  assert(rendered.text.includes('Stream-A'), 'Should include stream ID');
  assert(rendered.text.includes('50%'), 'Should include progress');
  assert(rendered.text.includes('sonnet'), 'Should include model');
  assert(rendered.width > 0, 'Should have width');
});

runTest('Progress HUD: Calculates progress from status', () => {
  const pending = calculateProgress({
    taskId: 'T1', taskTitle: 'Test', status: 'pending', progressPercent: 0,
    activeFiles: [], lastUpdate: ''
  });
  assertEquals(pending, 0, 'Pending should be 0%');

  const inProgress = calculateProgress({
    taskId: 'T1', taskTitle: 'Test', status: 'in_progress', progressPercent: 0,
    activeFiles: [], lastUpdate: ''
  });
  assertEquals(inProgress, 50, 'In progress should be 50%');

  const completed = calculateProgress({
    taskId: 'T1', taskTitle: 'Test', status: 'completed', progressPercent: 0,
    activeFiles: [], lastUpdate: ''
  });
  assertEquals(completed, 100, 'Completed should be 100%');
});

runTest('Progress HUD: Renders different models with colors', () => {
  const state = {
    taskId: 'TASK-123',
    taskTitle: 'Test',
    status: 'in_progress' as const,
    progressPercent: 50,
    activeFiles: [],
    lastUpdate: new Date().toISOString()
  };

  const haiku = renderStatusline(state, 'haiku', 500, { useColor: false });
  assert(haiku.text.includes('haiku'), 'Should show haiku');

  const sonnet = renderStatusline(state, 'sonnet', 1000, { useColor: false });
  assert(sonnet.text.includes('sonnet'), 'Should show sonnet');

  const opus = renderStatusline(state, 'opus', 2000, { useColor: false });
  assert(opus.text.includes('opus'), 'Should show opus');
});

runTest('Progress HUD: Creates statusline updater', () => {
  const updater = createStatusline('TASK-123', 'Test Task', 'Stream-A');

  const state = updater.getState();
  assertEquals(state.taskId, 'TASK-123', 'Should have task ID');
  assertEquals(state.taskTitle, 'Test Task', 'Should have task title');
  assertEquals(state.streamId, 'Stream-A', 'Should have stream ID');
  assertEquals(state.status, 'pending', 'Should start as pending');
});

runTest('Progress HUD: Updates state and re-renders', () => {
  const updater = createStatusline('TASK-123', 'Test Task');

  const rendered1 = updater.updateState({ status: 'in_progress', progressPercent: 25 });
  assert(rendered1.text.includes('25%'), 'Should update progress');

  const rendered2 = updater.updateModel('opus');
  assert(rendered2.text.includes('opus'), 'Should update model');
});

runTest('Progress HUD: Handles file tracking', () => {
  const state = {
    taskId: 'TASK-123',
    taskTitle: 'Test',
    status: 'in_progress' as const,
    progressPercent: 50,
    activeFiles: ['src/auth.ts', 'src/api.ts', 'src/db.ts'],
    lastUpdate: new Date().toISOString()
  };

  const rendered = renderStatusline(state, 'sonnet', 1000, { showFiles: true });
  assert(rendered.text.includes('3 files'), 'Should show file count');
});

// ============================================================================
// FEATURE 4: SKILL EXTRACTION - PATTERN DETECTION
// ============================================================================

runTest('Skill Extraction: File structure exists', () => {
  const patternDetectionPath = join(process.cwd(), 'mcp-servers/copilot-memory/src/tools/pattern-detection.ts');
  assert(existsSync(patternDetectionPath), 'Pattern detection module should exist');

  const content = readFileSync(patternDetectionPath, 'utf-8');
  assert(content.includes('detectFilePatterns'), 'Should have detectFilePatterns function');
  assert(content.includes('detectKeywords'), 'Should have detectKeywords function');
});

runTest('Skill Extraction: Skill extraction tests exist', () => {
  const testPath = join(process.cwd(), 'mcp-servers/copilot-memory/src/tools/__tests__/skill-extraction.test.ts');
  assert(existsSync(testPath), 'Skill extraction tests should exist');
});

runTest('Skill Extraction: OMC types defined', () => {
  const typesPath = join(process.cwd(), 'mcp-servers/task-copilot/src/types/omc-features.ts');
  assert(existsSync(typesPath), 'OMC feature types should exist');

  const content = readFileSync(typesPath, 'utf-8');
  assert(content.includes('PatternCandidate'), 'Should have PatternCandidate type');
  assert(content.includes('SkillExtractionResult'), 'Should have SkillExtractionResult type');
});

// ============================================================================
// FEATURE 5: ZERO-CONFIG INSTALL
// ============================================================================

runTest('Zero-Config Install: Installer package exists', () => {
  const installerPath = join(process.cwd(), 'packages/installer/README.md');
  assert(existsSync(installerPath), 'Installer package should exist');

  const content = readFileSync(installerPath, 'utf-8');
  assert(content.includes('npx'), 'Should document npx usage');
  assert(content.includes('claude-copilot install'), 'Should document install command');
});

runTest('Zero-Config Install: Dependency checker documented', () => {
  const installerPath = join(process.cwd(), 'packages/installer/README.md');
  const content = readFileSync(installerPath, 'utf-8');

  assert(content.includes('check'), 'Should have check command');
  assert(content.includes('validate'), 'Should have validate command');
  assert(content.includes('auto-fix'), 'Should have auto-fix option');
});

runTest('Zero-Config Install: Installation options', () => {
  const installerPath = join(process.cwd(), 'packages/installer/README.md');
  const content = readFileSync(installerPath, 'utf-8');

  assert(content.includes('--global'), 'Should support global install');
  assert(content.includes('--project'), 'Should support project install');
  assert(content.includes('--skip-deps'), 'Should support skipping deps');
  assert(content.includes('--skip-build'), 'Should support skipping build');
});

runTest('Zero-Config Install: Platform support', () => {
  const installerPath = join(process.cwd(), 'packages/installer/README.md');
  const content = readFileSync(installerPath, 'utf-8');

  assert(content.includes('macOS'), 'Should support macOS');
  assert(content.includes('Linux'), 'Should support Linux');
  assert(content.includes('Homebrew'), 'Should mention Homebrew for macOS');
});

// ============================================================================
// INTEGRATION TESTS
// ============================================================================

runTest('Integration: Ecomode + Magic Keywords', () => {
  // Parse keywords first
  const parsed = parseKeywords('eco: fix: login authentication bug');

  assert(parsed.valid, 'Should be valid');

  // Route with modifier
  const result = routeToModel({
    title: parsed.originalMessage,
    description: 'JWT token validation failing',
    fileCount: 2,
    agentId: 'qa'
  });

  // eco: should use complexity-based routing
  assert(result.modifier !== null, 'Should detect eco: modifier');
  assert(['haiku', 'sonnet', 'opus'].includes(result.route.model), 'Should route to valid model');
});

runTest('Integration: Magic Keywords + Progress HUD', () => {
  // Parse command
  const parsed = parseKeywords('fast: test: the authentication flow');

  // Create statusline for task
  const updater = createStatusline('TASK-456', parsed.cleanMessage, 'Stream-B');

  // Update with progress
  updater.updateState({ status: 'in_progress', progressPercent: 30 });
  updater.updateModel('haiku'); // fast: suggests haiku

  const rendered = updater.render();

  assert(rendered.text.includes('30%'), 'Should show progress');
  assert(rendered.text.includes('haiku'), 'Should show haiku model');
  assert(rendered.text.includes('Stream-B'), 'Should show stream ID');
});

runTest('Integration: Complete workflow simulation', () => {
  // User message with keywords
  const userMessage = 'eco: add: user profile dashboard';

  // Step 1: Parse keywords
  const parsed = parseKeywords(userMessage);
  assert(parsed.valid, 'Keywords should be valid');
  assert(parsed.modifier?.keyword === 'eco', 'Should have eco modifier');
  assert(parsed.action?.keyword === 'add', 'Should have add action');

  // Step 2: Route to model based on complexity
  const routing = routeToModel({
    title: parsed.cleanMessage,
    description: 'Create user profile page with settings and preferences',
    fileCount: 5,
    agentId: 'me'
  });

  assert(['haiku', 'sonnet', 'opus'].includes(routing.route.model), 'Should route to model');

  // Step 3: Create progress HUD
  const hud = createStatusline('TASK-789', parsed.cleanMessage, 'Stream-C');
  hud.updateModel(routing.route.model);
  hud.updateState({ status: 'in_progress', progressPercent: 15 });

  const statusline = hud.render();
  assert(statusline.text.includes('15%'), 'Should show progress');
  assert(statusline.text.includes(routing.route.model), 'Should show routed model');
});

// ============================================================================
// TEST SUMMARY
// ============================================================================

setTimeout(() => {
  console.log('\n' + '='.repeat(80));
  console.log('OMC FEATURES INTEGRATION TEST SUMMARY');
  console.log('='.repeat(80));

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  const skipped = results.filter(r => r.status === 'SKIP').length;
  const total = results.length;

  console.log(`\nTotal Tests: ${total}`);
  console.log(`✅ Passed: ${passed}`);
  console.log(`❌ Failed: ${failed}`);
  console.log(`⏭️  Skipped: ${skipped}`);

  if (failed > 0) {
    console.log('\nFailed Tests:');
    results
      .filter(r => r.status === 'FAIL')
      .forEach(r => {
        console.log(`  - ${r.testName}`);
        console.log(`    Error: ${r.error}`);
      });
  }

  const avgDuration = results.reduce((sum, r) => sum + r.duration, 0) / results.length;
  console.log(`\nAverage Test Duration: ${avgDuration.toFixed(2)}ms`);

  console.log('\n' + '='.repeat(80));

  process.exit(failed > 0 ? 1 : 0);
}, 2000); // Wait for all async tests to complete
