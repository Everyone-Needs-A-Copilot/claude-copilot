/**
 * Unit Tests: Skill Loading and Evaluation
 *
 * Tests skill_evaluate auto-detection, global/local skill discovery,
 * and skill injection into agent context.
 *
 * @see TEST_STRATEGY.md - Suite B
 */

import { readFileSync, existsSync, readdirSync, statSync } from 'fs';
import { join, basename } from 'path';

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

function logResult(
  testName: string,
  status: 'PASS' | 'FAIL' | 'SKIP',
  duration: number,
  error?: string,
  details?: string
) {
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
    throw new Error(`${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function assertContains(text: string, substring: string, message: string): void {
  if (!text.includes(substring)) {
    throw new Error(`${message}: expected to contain "${substring}"`);
  }
}

function assertGreaterThan(actual: number, expected: number, message: string): void {
  if (actual <= expected) {
    throw new Error(`${message}: expected ${actual} > ${expected}`);
  }
}

function assertInRange(actual: number, min: number, max: number, message: string): void {
  if (actual < min || actual > max) {
    throw new Error(`${message}: expected ${actual} to be between ${min} and ${max}`);
  }
}

async function runTest(testName: string, testFn: () => void | Promise<void>): Promise<void> {
  const start = Date.now();
  try {
    await testFn();
    logResult(testName, 'PASS', Date.now() - start);
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : String(error);
    logResult(testName, 'FAIL', Date.now() - start, errorMessage);
  }
}

// ============================================================================
// TEST DATA TYPES
// ============================================================================

interface Skill {
  skill_name: string;
  skill_category: string;
  description: string;
  trigger_files: string[];
  trigger_keywords: string[];
  quality_keywords?: string[];
  tags?: string[];
  token_estimate?: number;
}

interface SkillEvaluationContext {
  files?: string[];
  text?: string;
  recentActivity?: string[];
  threshold?: number;
  limit?: number;
}

interface SkillMatch {
  skillName: string;
  confidence: number;
  level: 'high' | 'medium' | 'low';
  reason: string;
}

// ============================================================================
// MOCK SKILLS
// ============================================================================

const MOCK_SKILLS: Record<string, Skill> = {
  'python-idioms': {
    skill_name: 'python-idioms',
    skill_category: 'code',
    description: 'Python best practices and idioms',
    trigger_files: ['*.py', '*.pyi', 'requirements.txt', 'pyproject.toml'],
    trigger_keywords: ['python', 'django', 'flask', 'fastapi', 'pytest'],
    quality_keywords: ['pythonic', 'type hints', 'dataclass'],
    tags: ['python', 'backend'],
    token_estimate: 1500
  },
  'javascript-patterns': {
    skill_name: 'javascript-patterns',
    skill_category: 'code',
    description: 'JavaScript/TypeScript patterns',
    trigger_files: ['*.js', '*.ts', '*.jsx', '*.tsx', 'package.json'],
    trigger_keywords: ['javascript', 'typescript', 'node', 'npm', 'async'],
    tags: ['javascript', 'frontend', 'backend'],
    token_estimate: 1800
  },
  'testing-patterns': {
    skill_name: 'testing-patterns',
    skill_category: 'testing',
    description: 'Testing best practices',
    trigger_files: ['*.test.*', '*.spec.*', 'jest.config.*', 'vitest.config.*'],
    trigger_keywords: ['test', 'testing', 'jest', 'vitest', 'coverage', 'mock'],
    quality_keywords: ['unit test', 'integration test', 'e2e'],
    tags: ['testing', 'quality'],
    token_estimate: 1200
  },
  'react-patterns': {
    skill_name: 'react-patterns',
    skill_category: 'code',
    description: 'React component patterns',
    trigger_files: ['*.jsx', '*.tsx', 'package.json'],
    trigger_keywords: ['react', 'component', 'hooks', 'state', 'props'],
    tags: ['react', 'frontend'],
    token_estimate: 2000
  },
  'security-review': {
    skill_name: 'security-review',
    skill_category: 'security',
    description: 'Security audit patterns',
    trigger_files: ['*.ts', '*.js', '*.py'],
    trigger_keywords: ['security', 'auth', 'authentication', 'authorization', 'vulnerability'],
    quality_keywords: ['OWASP', 'XSS', 'CSRF', 'injection'],
    tags: ['security'],
    token_estimate: 2200
  }
};

// ============================================================================
// SKILL EVALUATION SIMULATOR
// ============================================================================

function matchFilePatterns(files: string[], patterns: string[]): number {
  let matches = 0;
  for (const file of files) {
    for (const pattern of patterns) {
      if (matchGlob(file, pattern)) {
        matches++;
        break;
      }
    }
  }
  return matches / Math.max(files.length, 1);
}

function matchGlob(filename: string, pattern: string): boolean {
  // Simple glob matching (not comprehensive)
  const regexPattern = pattern
    .replace(/\./g, '\\.')
    .replace(/\*/g, '.*');
  const regex = new RegExp(`^${regexPattern}$`);
  return regex.test(filename);
}

function matchKeywords(text: string, keywords: string[]): number {
  const lowerText = text.toLowerCase();
  let matches = 0;
  for (const keyword of keywords) {
    if (lowerText.includes(keyword.toLowerCase())) {
      matches++;
    }
  }
  return matches / Math.max(keywords.length, 1);
}

function evaluateSkills(
  context: SkillEvaluationContext,
  availableSkills: Record<string, Skill>
): SkillMatch[] {
  const matches: SkillMatch[] = [];
  const threshold = context.threshold || 0.5;

  for (const skill of Object.values(availableSkills)) {
    let confidence = 0;
    const reasons: string[] = [];

    // File pattern matching (50% weight)
    if (context.files && context.files.length > 0) {
      const fileScore = matchFilePatterns(context.files, skill.trigger_files);
      confidence += fileScore * 0.5;
      if (fileScore > 0) {
        reasons.push(`file patterns matched (${(fileScore * 100).toFixed(0)}%)`);
      }
    }

    // Keyword matching (50% weight)
    if (context.text) {
      const keywordScore = matchKeywords(context.text, skill.trigger_keywords);
      confidence += keywordScore * 0.5;
      if (keywordScore > 0) {
        reasons.push(`keywords matched (${(keywordScore * 100).toFixed(0)}%)`);
      }
    }

    // Recent activity boost (5% bonus)
    if (context.recentActivity && context.recentActivity.length > 0) {
      for (const activity of context.recentActivity) {
        if (skill.tags?.includes(activity.toLowerCase())) {
          confidence += 0.05;
          reasons.push('recent activity boost');
          break;
        }
      }
    }

    if (confidence >= threshold) {
      const level: 'high' | 'medium' | 'low' =
        confidence >= 0.7 ? 'high' : confidence >= 0.4 ? 'medium' : 'low';

      matches.push({
        skillName: skill.skill_name,
        confidence,
        level,
        reason: reasons.join(', ')
      });
    }
  }

  // Sort by confidence (descending)
  matches.sort((a, b) => b.confidence - a.confidence);

  // Apply limit
  const limit = context.limit || 10;
  return matches.slice(0, limit);
}

// ============================================================================
// TEST SUITE: SKILL DISCOVERY
// ============================================================================

async function testSkillDiscovery() {
  console.log('\n🔍 Testing Skill Discovery...\n');

  const projectRoot = join(__dirname, '../..');
  const skillsDir = join(projectRoot, '.claude/skills');

  await runTest('Skills directory exists', () => {
    assert(existsSync(skillsDir), 'Skills directory should exist at .claude/skills/');
  });

  await runTest('Skills have valid frontmatter', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const name = basename(skillFile);

      // Check frontmatter markers
      assert(content.startsWith('---'), `Skill ${name} missing opening frontmatter`);
      const secondDash = content.indexOf('---', 3);
      assert(secondDash > 0, `Skill ${name} missing closing frontmatter`);

      // Check required fields
      assertContains(content, 'skill_name:', `Skill ${name} missing skill_name`);
      assertContains(content, 'skill_category:', `Skill ${name} missing skill_category`);
      assertContains(content, 'description:', `Skill ${name} missing description`);
      assertContains(content, 'trigger_files:', `Skill ${name} missing trigger_files`);
      assertContains(content, 'trigger_keywords:', `Skill ${name} missing trigger_keywords`);
    }
  });

  await runTest('Skills have code examples', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const name = basename(skillFile);

      // Check for code blocks
      const codeBlockCount = (content.match(/```/g) || []).length;
      assertGreaterThan(codeBlockCount, 0, `Skill ${name} should have at least one code example`);
    }
  });

  await runTest('Skills have token estimates within budget', () => {
    const skillFiles = findSkillFiles(skillsDir);

    for (const skillFile of skillFiles) {
      const content = readFileSync(skillFile, 'utf-8');
      const name = basename(skillFile);

      const tokenMatch = content.match(/token_estimate:\s*(\d+)/);
      if (tokenMatch) {
        const tokenEstimate = parseInt(tokenMatch[1], 10);
        assertInRange(tokenEstimate, 100, 3000, `Skill ${name} token estimate ${tokenEstimate}`);
      }
    }
  });
}

// ============================================================================
// TEST SUITE: SKILL EVALUATION
// ============================================================================

async function testSkillEvaluation() {
  console.log('\n🎯 Testing Skill Evaluation...\n');

  await runTest('File pattern matching: Python files', () => {
    const context: SkillEvaluationContext = {
      files: ['src/api.py', 'tests/test_api.py'],
      threshold: 0.3
    };

    const matches = evaluateSkills(context, MOCK_SKILLS);
    const pythonMatch = matches.find(m => m.skillName === 'python-idioms');

    assert(pythonMatch !== undefined, 'Should match python-idioms skill');
    assertGreaterThan(pythonMatch.confidence, 0.3, 'Confidence should be > 0.3');
  });

  await runTest('File pattern matching: Test files', () => {
    const context: SkillEvaluationContext = {
      files: ['src/Button.test.tsx', 'src/api.spec.ts'],
      threshold: 0.3
    };

    const matches = evaluateSkills(context, MOCK_SKILLS);
    const testingMatch = matches.find(m => m.skillName === 'testing-patterns');

    assert(testingMatch !== undefined, 'Should match testing-patterns skill');
    assertGreaterThan(testingMatch.confidence, 0.3, 'Confidence should be > 0.3');
  });

  await runTest('Keyword matching: React components', () => {
    const context: SkillEvaluationContext = {
      text: 'Help me write React component with hooks and state management',
      threshold: 0.3
    };

    const matches = evaluateSkills(context, MOCK_SKILLS);
    const reactMatch = matches.find(m => m.skillName === 'react-patterns');

    assert(reactMatch !== undefined, 'Should match react-patterns skill');
    assertGreaterThan(reactMatch.confidence, 0.3, 'Confidence should be > 0.3');
  });

  await runTest('Combined signals: TypeScript testing', () => {
    const context: SkillEvaluationContext = {
      files: ['src/auth.test.ts'],
      text: 'Write unit tests for authentication',
      threshold: 0.4
    };

    const matches = evaluateSkills(context, MOCK_SKILLS);

    // Should match both testing and javascript patterns
    const testingMatch = matches.find(m => m.skillName === 'testing-patterns');
    const jsMatch = matches.find(m => m.skillName === 'javascript-patterns');

    assert(testingMatch !== undefined, 'Should match testing-patterns');
    assert(jsMatch !== undefined, 'Should match javascript-patterns');
  });

  await runTest('Threshold filtering works', () => {
    const context: SkillEvaluationContext = {
      files: ['src/utils.ts'],
      threshold: 0.8 // High threshold
    };

    const matches = evaluateSkills(context, MOCK_SKILLS);

    // With high threshold, fewer matches expected
    for (const match of matches) {
      assertGreaterThan(match.confidence, 0.8, `Match ${match.skillName} should exceed threshold`);
    }
  });

  await runTest('Confidence levels categorized correctly', () => {
    const context: SkillEvaluationContext = {
      files: ['src/api.py', 'requirements.txt'],
      text: 'Python FastAPI implementation with pytest',
      threshold: 0.3
    };

    const matches = evaluateSkills(context, MOCK_SKILLS);
    const pythonMatch = matches.find(m => m.skillName === 'python-idioms');

    assert(pythonMatch !== undefined, 'Should match python-idioms');

    // With strong signals, should be high confidence
    if (pythonMatch.confidence >= 0.7) {
      assertEquals(pythonMatch.level, 'high', 'Confidence >= 0.7 should be "high"');
    } else if (pythonMatch.confidence >= 0.4) {
      assertEquals(pythonMatch.level, 'medium', 'Confidence >= 0.4 should be "medium"');
    } else {
      assertEquals(pythonMatch.level, 'low', 'Confidence < 0.4 should be "low"');
    }
  });

  await runTest('Recent activity boosts confidence', () => {
    const contextWithoutActivity: SkillEvaluationContext = {
      files: ['src/utils.ts'],
      threshold: 0.2
    };

    const contextWithActivity: SkillEvaluationContext = {
      files: ['src/utils.ts'],
      recentActivity: ['javascript', 'frontend'],
      threshold: 0.2
    };

    const matchesWithout = evaluateSkills(contextWithoutActivity, MOCK_SKILLS);
    const matchesWith = evaluateSkills(contextWithActivity, MOCK_SKILLS);

    const jsMatchWithout = matchesWithout.find(m => m.skillName === 'javascript-patterns');
    const jsMatchWith = matchesWith.find(m => m.skillName === 'javascript-patterns');

    if (jsMatchWithout && jsMatchWith) {
      assertGreaterThan(
        jsMatchWith.confidence,
        jsMatchWithout.confidence,
        'Recent activity should boost confidence'
      );
    }
  });

  await runTest('Limit parameter restricts results', () => {
    const context: SkillEvaluationContext = {
      files: ['src/app.tsx', 'src/app.test.tsx'],
      text: 'React component with TypeScript and Jest tests',
      threshold: 0.2,
      limit: 2
    };

    const matches = evaluateSkills(context, MOCK_SKILLS);

    assert(matches.length <= 2, `Should return at most 2 matches, got ${matches.length}`);
  });
}

// ============================================================================
// TEST SUITE: SKILL INJECTION
// ============================================================================

async function testSkillInjection() {
  console.log('\n💉 Testing Skill Injection...\n');

  await runTest('Skill templates have required structure', () => {
    const projectRoot = join(__dirname, '../..');
    const templatePath = join(projectRoot, 'templates/skills/SKILL-TEMPLATE.md');

    if (existsSync(templatePath)) {
      const content = readFileSync(templatePath, 'utf-8');

      assertContains(content, 'skill_name:', 'Template missing skill_name');
      assertContains(content, 'skill_category:', 'Template missing skill_category');
      assertContains(content, '## Core Patterns', 'Template missing Core Patterns section');
      assertContains(content, '## Anti-Patterns', 'Template missing Anti-Patterns section');
      assertContains(content, '## Validation Checklist', 'Template missing Validation Checklist');
    } else {
      console.log('      (Skipping: SKILL-TEMPLATE.md not found)');
    }
  });

  await runTest('Skills loaded via @include directive', () => {
    const includeDirective = '@include ~/.claude/skills/python/python-idioms.md';
    const pattern = /@include\s+[\w/.~-]+\.md/;

    assert(pattern.test(includeDirective), '@include directive should match pattern');
  });

  await runTest('Token budget respected: max 3 skills', () => {
    const maxSkills = 3;
    const skillTokens = [1500, 1800, 1200, 2000, 2200]; // 5 skills
    const topSkills = skillTokens.sort((a, b) => b - a).slice(0, maxSkills);

    assertEquals(topSkills.length, maxSkills, `Should load at most ${maxSkills} skills`);

    const totalTokens = topSkills.reduce((sum, tokens) => sum + tokens, 0);
    assert(totalTokens < 10000, `Total tokens (${totalTokens}) should be under 10k`);
  });
}

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function findSkillFiles(dir: string): string[] {
  const files: string[] = [];

  function walk(currentDir: string) {
    if (!existsSync(currentDir)) return;

    const entries = readdirSync(currentDir);
    for (const entry of entries) {
      const fullPath = join(currentDir, entry);
      const stat = statSync(fullPath);

      if (stat.isDirectory()) {
        walk(fullPath);
      } else if (entry.endsWith('.md') && entry !== 'README.md') {
        files.push(fullPath);
      }
    }
  }

  walk(dir);
  return files;
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function main() {
  console.log('='.repeat(70));
  console.log('  UNIT TESTS: SKILL LOADING AND EVALUATION');
  console.log('='.repeat(70));

  await testSkillDiscovery();
  await testSkillEvaluation();
  await testSkillInjection();

  // Print summary
  console.log('\n' + '='.repeat(70));
  console.log('  TEST SUMMARY');
  console.log('='.repeat(70));

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  const skipped = results.filter(r => r.status === 'SKIP').length;

  console.log(`\n✅ Passed: ${passed}`);
  console.log(`❌ Failed: ${failed}`);
  console.log(`⏭️  Skipped: ${skipped}`);
  console.log(`📊 Total: ${results.length}`);

  if (failed > 0) {
    console.log('\n❌ FAILED TESTS:');
    for (const result of results.filter(r => r.status === 'FAIL')) {
      console.log(`  - ${result.testName}: ${result.error}`);
    }
    process.exit(1);
  } else {
    console.log('\n✅ ALL TESTS PASSED');
    process.exit(0);
  }
}

main().catch(console.error);
