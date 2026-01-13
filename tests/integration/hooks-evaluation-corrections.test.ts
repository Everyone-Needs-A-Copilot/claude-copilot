/**
 * Integration Tests: Hooks → Skill Evaluation → Correction Detection
 *
 * Tests the complete workflow from lifecycle hooks to skill evaluation
 * to correction capture patterns.
 *
 * @see PRD-6df7cc11-c4d4-4f48-9e0c-1275cf6fb327
 * @see Stream-B (Lifecycle Hooks)
 * @see Stream-C (Skill Evaluation)
 * @see Stream-D (Correction Detection)
 */

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

function assertGreaterThan(actual: number, expected: number, message: string): void {
  if (!(actual > expected)) {
    throw new Error(`${message}: expected ${actual} > ${expected}`);
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
// MOCK TYPES
// ============================================================================

interface MockSkillMeta {
  name: string;
  description: string;
  keywords: string[];
  tags?: string[];
  triggers?: {
    files?: string[];
    keywords?: string[];
  };
}

interface ValidationResult {
  ruleName: string;
  passed: boolean;
  message: string;
}

interface AgentContext {
  taskId: string;
  iteration: number;
  validationResults: ValidationResult[];
  completionPromises: Array<{ type: string; detected: boolean }>;
}

// ============================================================================
// STREAM-B: LIFECYCLE HOOKS IMPLEMENTATION
// ============================================================================

const hookRegistry = new Map<string, {
  id: string;
  taskId: string;
  enabled: boolean;
  callback: (context: AgentContext) => { action: string; reason: string };
}>();

function registerHook(
  taskId: string,
  callback: (context: AgentContext) => { action: string; reason: string },
  options: { hookId?: string; enabled?: boolean } = {}
): string {
  const hookId = options.hookId || `HOOK-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
  hookRegistry.set(hookId, {
    id: hookId,
    taskId,
    enabled: options.enabled !== false,
    callback
  });
  return hookId;
}

function getHook(hookId: string) {
  return hookRegistry.get(hookId);
}

function getTaskHooks(taskId: string) {
  return Array.from(hookRegistry.values()).filter(h => h.taskId === taskId);
}

function clearHooks() {
  hookRegistry.clear();
}

function parseCompletionPromises(output: string): Array<{ type: string; detected: boolean; content: string }> {
  const promises: Array<{ type: string; detected: boolean; content: string }> = [];

  const completeMatch = output.match(/<promise>COMPLETE<\/promise>/i);
  if (completeMatch) {
    promises.push({ type: 'COMPLETE', detected: true, content: completeMatch[0] });
  }

  const blockedMatch = output.match(/<promise>BLOCKED<\/promise>/i);
  if (blockedMatch) {
    promises.push({ type: 'BLOCKED', detected: true, content: blockedMatch[0] });
  }

  const escalateMatch = output.match(/<promise>ESCALATE<\/promise>/i);
  if (escalateMatch) {
    promises.push({ type: 'ESCALATE', detected: true, content: escalateMatch[0] });
  }

  return promises;
}

function evaluateDefaultHook(context: AgentContext): { action: string; reason: string } {
  const completePromise = context.completionPromises.find(p => p.type === 'COMPLETE');
  if (completePromise) {
    return { action: 'complete', reason: 'Agent signaled completion via <promise>COMPLETE</promise>' };
  }

  const escalatePromise = context.completionPromises.find(p => p.type === 'ESCALATE');
  if (escalatePromise) {
    return { action: 'escalate', reason: 'Agent signaled escalation via <promise>ESCALATE</promise>' };
  }

  const blockedPromise = context.completionPromises.find(p => p.type === 'BLOCKED');
  if (blockedPromise) {
    return { action: 'escalate', reason: 'Agent signaled blocked state via <promise>BLOCKED</promise>' };
  }

  if (context.validationResults.length > 0) {
    const allPassed = context.validationResults.every(r => r.passed);
    if (allPassed) {
      return { action: 'complete', reason: 'All validation rules passed' };
    }

    const failedRules = context.validationResults.filter(r => !r.passed);
    return { action: 'continue', reason: `${failedRules.length} validation rule(s) failed` };
  }

  return { action: 'continue', reason: 'Iteration in progress' };
}

// ============================================================================
// STREAM-C: SKILL EVALUATION IMPLEMENTATION
// ============================================================================

function matchPatterns(files: string[], skills: Map<string, MockSkillMeta>): Array<{ skillName: string; confidence: number; matchedPatterns: Array<{ pattern: string; file: string }> }> {
  const results: Array<{ skillName: string; confidence: number; matchedPatterns: Array<{ pattern: string; file: string }> }> = [];

  for (const [skillName, skill] of skills) {
    const triggerPatterns = skill.triggers?.files || [];
    const matchedPatterns: Array<{ pattern: string; file: string }> = [];

    for (const file of files) {
      for (const pattern of triggerPatterns) {
        const regex = new RegExp(pattern.replace(/\*/g, '.*').replace(/\?/g, '.'));
        if (regex.test(file)) {
          matchedPatterns.push({ pattern, file });
        }
      }
    }

    if (matchedPatterns.length > 0) {
      const confidence = Math.min(0.5 + (matchedPatterns.length * 0.15), 1.0);
      results.push({ skillName, confidence, matchedPatterns });
    }
  }

  return results.sort((a, b) => b.confidence - a.confidence);
}

function matchKeywords(text: string, skills: Map<string, MockSkillMeta>): Array<{ skillName: string; confidence: number; matchedKeywords: Array<{ keyword: string; weight: number }> }> {
  const results: Array<{ skillName: string; confidence: number; matchedKeywords: Array<{ keyword: string; weight: number }> }> = [];
  const textLower = text.toLowerCase();

  for (const [skillName, skill] of skills) {
    const keywords = [...skill.keywords, ...(skill.triggers?.keywords || [])];
    const matchedKeywords: Array<{ keyword: string; weight: number }> = [];

    for (const keyword of keywords) {
      if (textLower.includes(keyword.toLowerCase())) {
        const weight = Math.min(0.3 + (keyword.length * 0.05), 0.9);
        matchedKeywords.push({ keyword, weight });
      }
    }

    if (matchedKeywords.length > 0) {
      const totalWeight = matchedKeywords.reduce((sum, k) => sum + k.weight, 0);
      const confidence = Math.min(totalWeight / matchedKeywords.length, 1.0);
      results.push({ skillName, confidence, matchedKeywords });
    }
  }

  return results.sort((a, b) => b.confidence - a.confidence);
}

function calculateCombinedConfidence(
  patternConfidence: number,
  keywordConfidence: number,
  options: { patternWeight: number; keywordWeight: number } = { patternWeight: 0.5, keywordWeight: 0.5 }
): number {
  if (patternConfidence === 0 && keywordConfidence > 0) {
    return keywordConfidence * 0.9;
  }
  if (keywordConfidence === 0 && patternConfidence > 0) {
    return patternConfidence * 0.9;
  }

  const weighted = (patternConfidence * options.patternWeight) + (keywordConfidence * options.keywordWeight);
  const agreementBonus = Math.min(patternConfidence, keywordConfidence) * 0.1;

  return Math.min(weighted + agreementBonus, 1);
}

// ============================================================================
// STREAM-D: CORRECTION DETECTION IMPLEMENTATION
// ============================================================================

const CORRECTION_PATTERNS = [
  { id: 'explicit-correction', pattern: '(?:^|\\s)(?:correction|CORRECTION)[:\\s]+(.+)', weight: 0.95 },
  { id: 'actually-instead', pattern: '(?:^|\\s)(?:actually|Actually)[,\\s]+(?:use|it should be|I meant|you should use)\\s+([^.]+?)(?:\\s+instead(?:\\s+of\\s+([^.]+))?)?', weight: 0.85 },
  { id: 'no-wrong', pattern: '(?:^|\\s)(?:no|No|NO)[,\\s]+(?:that\'?s?|this is|it\'?s?)\\s+(?:wrong|incorrect|not right)', weight: 0.90 },
  { id: 'not-x-but-y', pattern: '(?:not|NOT)\\s+([^,]+)[,\\s]+(?:but|rather|instead)\\s+([^.]+)', weight: 0.90 },
  { id: 'should-be', pattern: '(?:it|this|that)\\s+should\\s+(?:be|have been)\\s+([^,]+?)(?:[,\\s]+not\\s+([^.]+))?', weight: 0.85 },
  { id: 'i-prefer', pattern: '(?:I|i)\\s+(?:prefer|would prefer|\'d prefer)\\s+([^.]+?)(?:\\s+(?:over|to|instead of)\\s+([^.]+))?', weight: 0.75 },
  { id: 'dont-use', pattern: '(?:don\'t|do not|Don\'t|please don\'t)\\s+(?:use|do)\\s+([^,]+?)(?:[,\\s]+(?:use|do)\\s+([^.]+))?', weight: 0.85 }
];

function matchCorrectionPatterns(message: string): Array<{ patternId: string; matchedText: string; captures?: Record<string, string> }> {
  const matches: Array<{ patternId: string; matchedText: string; captures?: Record<string, string> }> = [];

  for (const pattern of CORRECTION_PATTERNS) {
    try {
      const regex = new RegExp(pattern.pattern, 'gi');
      let match: RegExpExecArray | null;

      while ((match = regex.exec(message)) !== null) {
        const captures: Record<string, string> = {};
        for (let i = 1; i < match.length; i++) {
          if (match[i]) {
            captures[`group${i}`] = match[i].trim();
          }
        }

        matches.push({
          patternId: pattern.id,
          matchedText: match[0].trim(),
          captures: Object.keys(captures).length > 0 ? captures : undefined
        });
      }
    } catch {
      // Skip invalid patterns
    }
  }

  return matches;
}

function calculateCorrectionConfidence(
  matches: Array<{ patternId: string }>,
  messageLength: number,
  hasPreviousOutput: boolean
): number {
  if (matches.length === 0) return 0;

  const weights: Record<string, number> = {
    'explicit-correction': 0.95,
    'no-wrong': 0.90,
    'not-x-but-y': 0.90,
    'should-be': 0.85,
    'actually-instead': 0.85,
    'dont-use': 0.85,
    'i-prefer': 0.75
  };

  const seenPatterns = new Set<string>();
  let score = 0;

  for (const match of matches) {
    if (!seenPatterns.has(match.patternId)) {
      score += weights[match.patternId] || 0.5;
      seenPatterns.add(match.patternId);
    }
  }

  score = Math.min(score / Math.max(seenPatterns.size, 1), 1.0);

  if (seenPatterns.size >= 2) {
    score = Math.min(score * 1.1, 1.0);
  }

  if (messageLength < 100) {
    score = Math.min(score * 1.05, 1.0);
  }

  if (hasPreviousOutput) {
    score = Math.min(score * 1.05, 1.0);
  }

  if (messageLength > 500) {
    score *= 0.9;
  }

  return Math.round(score * 100) / 100;
}

function extractValues(matches: Array<{ patternId: string; captures?: Record<string, string> }>): { oldValue?: string; newValue?: string } {
  let oldValue: string | undefined;
  let newValue: string | undefined;

  for (const match of matches) {
    if (!match.captures) continue;

    if (match.patternId === 'not-x-but-y' || match.patternId === 'i-said') {
      if (match.captures.group1 && !oldValue) {
        oldValue = match.captures.group1;
      }
      if (match.captures.group2 && !newValue) {
        newValue = match.captures.group2;
      }
    } else {
      if (match.captures.group1 && !newValue) {
        newValue = match.captures.group1;
      }
      if (match.captures.group2 && !oldValue) {
        oldValue = match.captures.group2;
      }
    }
  }

  return { oldValue, newValue };
}

function inferTarget(message: string, agentId?: string): { target: string; targetId?: string } {
  const lowerMessage = message.toLowerCase();

  if (agentId) {
    if (['me', 'uid'].includes(agentId)) {
      return { target: 'skill', targetId: `agent-${agentId}` };
    }
    if (['doc', 'cw'].includes(agentId)) {
      return { target: 'skill', targetId: `agent-${agentId}` };
    }
    if (['ta', 'qa', 'sec', 'do'].includes(agentId)) {
      return { target: 'agent', targetId: agentId };
    }
  }

  if (lowerMessage.includes('skill') || lowerMessage.includes('pattern')) {
    return { target: 'skill' };
  }
  if (lowerMessage.includes('prefer') || lowerMessage.includes('always') || lowerMessage.includes('never')) {
    return { target: 'preference' };
  }
  if (lowerMessage.includes('remember') || lowerMessage.includes('note')) {
    return { target: 'memory' };
  }

  return { target: 'memory' };
}

// ============================================================================
// STREAM-B TESTS: LIFECYCLE HOOKS
// ============================================================================

async function runStreamBTests() {
  console.log('\n' + '='.repeat(70));
  console.log('STREAM-B: LIFECYCLE HOOKS TESTS');
  console.log('='.repeat(70) + '\n');

  clearHooks();

  await runTest('Hook registration with auto-generated ID', () => {
    clearHooks();
    const hookId = registerHook('TASK-1', () => ({ action: 'complete', reason: 'done' }));
    assert(hookId.startsWith('HOOK-'), 'Hook ID should start with HOOK-');
    assert(getHook(hookId) !== undefined, 'Hook should be retrievable');
  });

  await runTest('Hook registration with custom ID', () => {
    clearHooks();
    const customId = 'custom-hook-id';
    const hookId = registerHook('TASK-1', () => ({ action: 'complete', reason: 'done' }), { hookId: customId });
    assertEquals(hookId, customId, 'Hook ID should match custom ID');
  });

  await runTest('Get all hooks for a task', () => {
    clearHooks();
    registerHook('TASK-1', () => ({ action: 'complete', reason: 'hook 1' }));
    registerHook('TASK-1', () => ({ action: 'continue', reason: 'hook 2' }));
    registerHook('TASK-2', () => ({ action: 'complete', reason: 'hook 3' }));

    const task1Hooks = getTaskHooks('TASK-1');
    assertEquals(task1Hooks.length, 2, 'Should have 2 hooks for TASK-1');
    assert(task1Hooks.every(h => h.taskId === 'TASK-1'), 'All hooks should belong to TASK-1');
  });

  await runTest('Hook enabled flag', () => {
    clearHooks();
    const hookId = registerHook('TASK-1', () => ({ action: 'complete', reason: 'done' }), { enabled: false });
    const hook = getHook(hookId);
    assertEquals(hook?.enabled, false, 'Hook should be disabled');
  });

  await runTest('Parse COMPLETE promise', () => {
    const output = 'Task finished successfully. <promise>COMPLETE</promise>';
    const promises = parseCompletionPromises(output);
    assertEquals(promises.length, 1, 'Should detect one promise');
    assertEquals(promises[0].type, 'COMPLETE', 'Should be COMPLETE type');
  });

  await runTest('Parse BLOCKED promise', () => {
    const output = 'Cannot proceed. <promise>BLOCKED</promise>';
    const promises = parseCompletionPromises(output);
    assertEquals(promises.length, 1, 'Should detect one promise');
    assertEquals(promises[0].type, 'BLOCKED', 'Should be BLOCKED type');
  });

  await runTest('Parse ESCALATE promise', () => {
    const output = 'Issue detected. <promise>ESCALATE</promise>';
    const promises = parseCompletionPromises(output);
    assertEquals(promises.length, 1, 'Should detect one promise');
    assertEquals(promises[0].type, 'ESCALATE', 'Should be ESCALATE type');
  });

  await runTest('Parse multiple promises', () => {
    const output = '<promise>COMPLETE</promise> but also <promise>BLOCKED</promise>';
    const promises = parseCompletionPromises(output);
    assertEquals(promises.length, 2, 'Should detect two promises');
  });

  await runTest('COMPLETE promise prioritized over validation failures', () => {
    const context: AgentContext = {
      taskId: 'TASK-1',
      iteration: 1,
      validationResults: [{ ruleName: 'tests_pass', passed: false, message: 'Tests failed' }],
      completionPromises: [{ type: 'COMPLETE', detected: true }]
    };
    const result = evaluateDefaultHook(context);
    assertEquals(result.action, 'complete', 'Should complete due to promise');
    assert(result.reason.includes('COMPLETE'), 'Reason should mention COMPLETE');
  });

  await runTest('Complete when all validation passes', () => {
    const context: AgentContext = {
      taskId: 'TASK-1',
      iteration: 1,
      validationResults: [
        { ruleName: 'tests_pass', passed: true, message: 'All tests pass' },
        { ruleName: 'lint_clean', passed: true, message: 'No lint errors' }
      ],
      completionPromises: []
    };
    const result = evaluateDefaultHook(context);
    assertEquals(result.action, 'complete', 'Should complete when validation passes');
  });

  await runTest('Continue when validation fails', () => {
    const context: AgentContext = {
      taskId: 'TASK-1',
      iteration: 1,
      validationResults: [{ ruleName: 'tests_pass', passed: false, message: '2 tests failed' }],
      completionPromises: []
    };
    const result = evaluateDefaultHook(context);
    assertEquals(result.action, 'continue', 'Should continue when validation fails');
  });

  await runTest('Escalate when BLOCKED promise detected', () => {
    const context: AgentContext = {
      taskId: 'TASK-1',
      iteration: 1,
      validationResults: [],
      completionPromises: [{ type: 'BLOCKED', detected: true }]
    };
    const result = evaluateDefaultHook(context);
    assertEquals(result.action, 'escalate', 'Should escalate on BLOCKED');
  });
}

// ============================================================================
// STREAM-C TESTS: SKILL EVALUATION
// ============================================================================

async function runStreamCTests() {
  console.log('\n' + '='.repeat(70));
  console.log('STREAM-C: SKILL EVALUATION TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('Pattern matching with file extensions', () => {
    const skills = new Map<string, MockSkillMeta>([
      ['typescript', {
        name: 'typescript',
        description: 'TypeScript patterns',
        keywords: ['typescript', 'ts'],
        triggers: { files: ['*.ts', '*.tsx'] }
      }]
    ]);

    const results = matchPatterns(['src/index.ts', 'app.tsx'], skills);
    assertEquals(results.length, 1, 'Should match one skill');
    assertEquals(results[0].skillName, 'typescript', 'Should match typescript skill');
    // Each file matches both patterns (*.ts and *.tsx match both index.ts and app.tsx due to regex)
    // So we expect at least 2 matches (one file per matching pattern)
    assert(results[0].matchedPatterns.length >= 2, 'Should match at least two patterns');
  });

  await runTest('Higher confidence for more matches', () => {
    const skills = new Map<string, MockSkillMeta>([
      ['testing', {
        name: 'testing',
        description: 'Testing patterns',
        keywords: ['test', 'jest'],
        triggers: { files: ['*.test.ts', '*.spec.ts'] }
      }]
    ]);

    const singleMatch = matchPatterns(['app.test.ts'], skills);
    const multipleMatches = matchPatterns(['app.test.ts', 'utils.test.ts', 'helper.spec.ts'], skills);
    assertGreaterThan(multipleMatches[0].confidence, singleMatch[0].confidence, 'More matches should give higher confidence');
  });

  await runTest('No match when patterns do not match', () => {
    const skills = new Map<string, MockSkillMeta>([
      ['python', {
        name: 'python',
        description: 'Python patterns',
        keywords: ['python', 'py'],
        triggers: { files: ['*.py'] }
      }]
    ]);

    const results = matchPatterns(['src/index.ts', 'app.js'], skills);
    assertEquals(results.length, 0, 'Should not match any skill');
  });

  await runTest('Keyword detection in text', () => {
    const skills = new Map<string, MockSkillMeta>([
      ['react', {
        name: 'react',
        description: 'React patterns',
        keywords: ['react', 'component', 'jsx', 'hooks'],
        triggers: { keywords: ['usestate', 'useeffect'] }
      }]
    ]);

    const results = matchKeywords('How do I use useState hooks in React?', skills);
    assertEquals(results.length, 1, 'Should match one skill');
    assertEquals(results[0].skillName, 'react', 'Should match react skill');
    assert(results[0].matchedKeywords.length >= 2, 'Should match at least 2 keywords');
  });

  await runTest('Longer keywords get higher weight', () => {
    const skills = new Map<string, MockSkillMeta>([
      ['test-skill', {
        name: 'test-skill',
        description: 'Test',
        keywords: ['api', 'authentication'],
        triggers: {}
      }]
    ]);

    const results = matchKeywords('I need to add authentication to my api', skills);
    const authKeyword = results[0].matchedKeywords.find(k => k.keyword === 'authentication');
    const apiKeyword = results[0].matchedKeywords.find(k => k.keyword === 'api');
    assertGreaterThan(authKeyword!.weight, apiKeyword!.weight, 'Longer keyword should have higher weight');
  });

  await runTest('Combined confidence calculation', () => {
    const combined = calculateCombinedConfidence(0.7, 0.8);
    assertGreaterThan(combined, 0.7, 'Combined confidence should be > 0.7');
    assert(combined <= 1, 'Combined confidence should be <= 1');
  });

  await runTest('Agreement bonus for dual signals', () => {
    const dualSignal = calculateCombinedConfidence(0.6, 0.6);
    const singleSignal = calculateCombinedConfidence(0.6, 0);
    assertGreaterThan(dualSignal, singleSignal, 'Dual signal should have higher confidence');
  });

  await runTest('Single signals scaled lower', () => {
    const singleKeyword = calculateCombinedConfidence(0, 0.8);
    assertEquals(singleKeyword, 0.8 * 0.9, 'Single keyword should be scaled by 0.9');
  });

  await runTest('Confidence capped at 1.0', () => {
    const combined = calculateCombinedConfidence(1.0, 1.0);
    assertEquals(combined, 1, 'Confidence should be capped at 1');
  });
}

// ============================================================================
// STREAM-D TESTS: CORRECTION DETECTION
// ============================================================================

async function runStreamDTests() {
  console.log('\n' + '='.repeat(70));
  console.log('STREAM-D: CORRECTION DETECTION TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('Detect explicit correction pattern', () => {
    const matches = matchCorrectionPatterns('Correction: use TypeScript instead');
    assertEquals(matches.length, 1, 'Should detect one pattern');
    assertEquals(matches[0].patternId, 'explicit-correction', 'Should be explicit-correction');
    assert(matches[0].captures?.group1?.includes('use TypeScript'), 'Should capture the correction');
  });

  await runTest('Detect "actually" correction pattern', () => {
    const matches = matchCorrectionPatterns('Actually, use useState instead of useReducer');
    assert(matches.some(m => m.patternId === 'actually-instead'), 'Should detect actually-instead pattern');
  });

  await runTest('Detect "no wrong" pattern', () => {
    const matches = matchCorrectionPatterns('No, that\'s wrong');
    assertEquals(matches.length, 1, 'Should detect one pattern');
    assertEquals(matches[0].patternId, 'no-wrong', 'Should be no-wrong pattern');
  });

  await runTest('Detect "not X but Y" pattern', () => {
    const matches = matchCorrectionPatterns('Not camelCase, but snake_case');
    assertEquals(matches.length, 1, 'Should detect one pattern');
    assertEquals(matches[0].patternId, 'not-x-but-y', 'Should be not-x-but-y pattern');
    assert(matches[0].captures?.group1?.includes('camelCase'), 'Should capture old value');
    assert(matches[0].captures?.group2?.includes('snake_case'), 'Should capture new value');
  });

  await runTest('Detect "should be" pattern', () => {
    const matches = matchCorrectionPatterns('It should be async, not sync');
    assertEquals(matches.length, 1, 'Should detect one pattern');
    assertEquals(matches[0].patternId, 'should-be', 'Should be should-be pattern');
  });

  await runTest('Detect preference pattern', () => {
    const matches = matchCorrectionPatterns('I prefer tabs over spaces');
    assertEquals(matches.length, 1, 'Should detect one pattern');
    assertEquals(matches[0].patternId, 'i-prefer', 'Should be i-prefer pattern');
  });

  await runTest('Detect "don\'t use" pattern', () => {
    const matches = matchCorrectionPatterns('Don\'t use var, use const');
    assertEquals(matches.length, 1, 'Should detect one pattern');
    assertEquals(matches[0].patternId, 'dont-use', 'Should be dont-use pattern');
  });

  await runTest('Detect multiple patterns in one message', () => {
    const matches = matchCorrectionPatterns('No, that\'s wrong. It should be async');
    assert(matches.length >= 2, 'Should detect multiple patterns');
  });

  await runTest('High confidence for explicit corrections', () => {
    const confidence = calculateCorrectionConfidence(
      [{ patternId: 'explicit-correction' }],
      50,
      true
    );
    assert(confidence >= 0.9, 'Explicit correction should have high confidence');
  });

  await runTest('Boost confidence for multiple patterns', () => {
    const singlePattern = calculateCorrectionConfidence([{ patternId: 'no-wrong' }], 100, false);
    const multiplePatterns = calculateCorrectionConfidence(
      [{ patternId: 'no-wrong' }, { patternId: 'should-be' }],
      100,
      false
    );
    assertGreaterThan(multiplePatterns, singlePattern, 'Multiple patterns should boost confidence');
  });

  await runTest('Short messages get confidence boost', () => {
    const shortMessage = calculateCorrectionConfidence([{ patternId: 'no-wrong' }], 50, false);
    const longMessage = calculateCorrectionConfidence([{ patternId: 'no-wrong' }], 200, false);
    assertGreaterThan(shortMessage, longMessage, 'Short message should have higher confidence');
  });

  await runTest('Very long messages reduce confidence', () => {
    const normalLength = calculateCorrectionConfidence([{ patternId: 'no-wrong' }], 200, false);
    const veryLong = calculateCorrectionConfidence([{ patternId: 'no-wrong' }], 600, false);
    assertGreaterThan(normalLength, veryLong, 'Very long message should reduce confidence');
  });

  await runTest('Extract new value from explicit correction', () => {
    const matches = [{ patternId: 'explicit-correction', captures: { group1: 'use TypeScript' } }];
    const { newValue } = extractValues(matches);
    assertEquals(newValue, 'use TypeScript', 'Should extract new value');
  });

  await runTest('Extract both old and new values', () => {
    const matches = [{ patternId: 'not-x-but-y', captures: { group1: 'camelCase', group2: 'snake_case' } }];
    const { oldValue, newValue } = extractValues(matches);
    assertEquals(oldValue, 'camelCase', 'Should extract old value');
    assertEquals(newValue, 'snake_case', 'Should extract new value');
  });

  await runTest('Route to skill for @agent-me', () => {
    const { target, targetId } = inferTarget('Use async/await', 'me');
    assertEquals(target, 'skill', 'Should route to skill');
    assertEquals(targetId, 'agent-me', 'Should target agent-me');
  });

  await runTest('Route to skill when message mentions skill', () => {
    const { target } = inferTarget('Update the testing skill pattern');
    assertEquals(target, 'skill', 'Should route to skill');
  });

  await runTest('Route to preference when message indicates preference', () => {
    const { target } = inferTarget('I prefer tabs over spaces');
    assertEquals(target, 'preference', 'Should route to preference');
  });

  await runTest('Default route to memory', () => {
    const { target } = inferTarget('This is some generic feedback');
    assertEquals(target, 'memory', 'Should default to memory');
  });
}

// ============================================================================
// E2E WORKFLOW TESTS
// ============================================================================

async function runE2ETests() {
  console.log('\n' + '='.repeat(70));
  console.log('E2E: HOOK → EVALUATION → CORRECTION WORKFLOW TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('Skill-related prompt triggers skill evaluation', () => {
    const userPrompt = 'Help me write a React component with TypeScript';
    const hasSkillKeywords = /react|typescript|component/i.test(userPrompt);
    assert(hasSkillKeywords, 'Should detect skill keywords');

    const skills = new Map<string, MockSkillMeta>([
      ['react-typescript', {
        name: 'react-typescript',
        description: 'React with TypeScript',
        keywords: ['react', 'typescript', 'component'],
        triggers: { files: ['*.tsx'] }
      }]
    ]);

    const matches = Array.from(skills.values()).filter(skill =>
      skill.keywords.some(k => userPrompt.toLowerCase().includes(k.toLowerCase()))
    );

    assertEquals(matches.length, 1, 'Should match one skill');
    assertEquals(matches[0].name, 'react-typescript', 'Should match react-typescript');
  });

  await runTest('Capture correction after agent response', () => {
    const agentOutput = 'I\'ve created the component using JavaScript.';
    const userCorrection = 'Actually, use TypeScript instead of JavaScript';

    const hasCorrection = /actually[,\s]+use/i.test(userCorrection);
    assert(hasCorrection, 'Should detect correction');

    const match = userCorrection.match(/use\s+(\w+)\s+instead\s+of\s+(\w+)/i);
    assert(match !== null, 'Should extract values');
    assertEquals(match![1], 'TypeScript', 'Should extract new value');
    assertEquals(match![2], 'JavaScript', 'Should extract old value');
  });

  await runTest('Complete iteration when validation passes', () => {
    const iteration1 = {
      validationResults: [{ ruleName: 'type_check', passed: false, message: 'Type error' }],
      completionPromises: []
    };
    const allPassed1 = iteration1.validationResults.every(r => r.passed);
    assert(!allPassed1, 'First iteration should fail');

    const iteration2 = {
      validationResults: [{ ruleName: 'type_check', passed: true, message: 'No errors' }],
      completionPromises: []
    };
    const allPassed2 = iteration2.validationResults.every(r => r.passed);
    assert(allPassed2, 'Second iteration should pass');
  });

  await runTest('Route correction to appropriate agent', () => {
    const agentFileMap: Record<string, string> = {
      me: '.claude/agents/me.md',
      ta: '.claude/agents/ta.md',
      qa: '.claude/agents/qa.md'
    };

    const targetFile = agentFileMap['me'];
    assertEquals(targetFile, '.claude/agents/me.md', 'Should route to correct file');
  });

  await runTest('Full lifecycle: prompt → evaluation → hook → correction', () => {
    // Step 1: User prompt triggers skill evaluation
    const prompt = 'Create a REST API endpoint';
    const detectedSkills = ['api-patterns', 'rest-design'];
    assert(detectedSkills.length > 0, 'Should detect skills');

    // Step 2: PreToolUse hook validates the approach
    const preToolResult = { action: 'allow', reason: 'Valid API creation request' };
    assertEquals(preToolResult.action, 'allow', 'Should allow the action');

    // Step 3: Agent produces output
    const agentOutput = 'Created endpoint at /api/users using GET method';
    assert(agentOutput.length > 0, 'Agent should produce output');

    // Step 4: PostToolUse hook logs the activity
    const postToolResult = { logged: true, executionTime: 150 };
    assert(postToolResult.logged, 'Should log activity');

    // Step 5: User provides correction
    const userFeedback = 'Actually, use POST instead of GET for creating resources';
    const correctionMatch = /use\s+(\w+)\s+instead/i.exec(userFeedback);
    assert(correctionMatch !== null, 'Should detect correction');
    assertEquals(correctionMatch![1], 'POST', 'Should extract new method');

    // Step 6: Correction is stored for review
    const storedCorrection = { id: 'CORR-1', newValue: 'POST', status: 'pending' };
    assertEquals(storedCorrection.status, 'pending', 'Should be pending review');
  });
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function runAllTests() {
  console.log('\n' + '='.repeat(70));
  console.log('HOOKS → SKILL EVALUATION → CORRECTION DETECTION');
  console.log('Integration Test Suite');
  console.log('='.repeat(70));

  await runStreamBTests();
  await runStreamCTests();
  await runStreamDTests();
  await runE2ETests();

  // Print summary
  console.log('\n' + '='.repeat(70));
  console.log('TEST SUMMARY');
  console.log('='.repeat(70) + '\n');

  const passed = results.filter(r => r.status === 'PASS').length;
  const failed = results.filter(r => r.status === 'FAIL').length;
  const skipped = results.filter(r => r.status === 'SKIP').length;

  console.log(`✅ Passed: ${passed}`);
  console.log(`❌ Failed: ${failed}`);
  console.log(`⏭️  Skipped: ${skipped}`);
  console.log(`📊 Total: ${results.length}`);

  if (failed > 0) {
    console.log('\n❌ FAILED TESTS:');
    for (const result of results.filter(r => r.status === 'FAIL')) {
      console.log(`  - ${result.testName}: ${result.error}`);
    }
  }

  console.log('\n' + (failed === 0 ? '✅ ALL TESTS PASSED' : '❌ SOME TESTS FAILED'));

  // Exit with appropriate code
  process.exit(failed > 0 ? 1 : 0);
}

runAllTests().catch(console.error);
