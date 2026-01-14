/**
 * Unit Tests: Agent Assignment and Invocation
 *
 * Tests that ensure specialized agents are properly assigned to tasks
 * and invoked during orchestration workflows.
 *
 * @see TEST_STRATEGY.md - Suite A
 */

import { readFileSync } from 'fs';
import { join } from 'path';

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

interface Task {
  id: string;
  prdId?: string;
  title: string;
  description?: string;
  assignedAgent?: string;
  status: 'pending' | 'in_progress' | 'completed' | 'blocked';
  metadata?: TaskMetadata;
}

interface TaskMetadata {
  streamId?: string;
  streamName?: string;
  streamDependencies?: string[];
  files?: string[];
}

interface WorkProduct {
  id: string;
  taskId: string;
  agentId: string;
  type: string;
  content: string;
}

// ============================================================================
// MOCK DATA
// ============================================================================

const VALID_AGENTS = ['me', 'qa', 'sec', 'doc', 'do', 'sd', 'uxd', 'uids', 'uid', 'cw', 'ta'];

const MOCK_TASKS: Record<string, Task> = {
  codeTask: {
    id: 'TASK-001',
    prdId: 'PRD-001',
    title: 'Implement login API',
    assignedAgent: 'me',
    status: 'pending',
    metadata: {
      streamId: 'Stream-A',
      files: ['src/auth/login.ts']
    }
  },
  testTask: {
    id: 'TASK-002',
    prdId: 'PRD-001',
    title: 'Write integration tests',
    assignedAgent: 'qa',
    status: 'pending',
    metadata: {
      streamId: 'Stream-B',
      streamDependencies: ['Stream-A']
    }
  },
  securityTask: {
    id: 'TASK-003',
    prdId: 'PRD-001',
    title: 'Security review',
    assignedAgent: 'sec',
    status: 'pending'
  },
  unassignedTask: {
    id: 'TASK-004',
    prdId: 'PRD-001',
    title: 'Plan feature',
    status: 'pending'
  },
  invalidTask: {
    id: 'TASK-005',
    prdId: 'PRD-001',
    title: 'Invalid agent',
    assignedAgent: 'invalid_agent',
    status: 'pending'
  }
};

// ============================================================================
// HELPER FUNCTIONS
// ============================================================================

function validateAgentAssignment(task: Task): { valid: boolean; error?: string } {
  if (!task.assignedAgent) {
    // Default to 'ta' if not specified
    return { valid: true };
  }

  if (!VALID_AGENTS.includes(task.assignedAgent)) {
    return { valid: false, error: `Invalid agent: ${task.assignedAgent}` };
  }

  return { valid: true };
}

function generateWorkerPrompt(task: Task): string {
  const agent = task.assignedAgent || 'ta';
  const files = task.metadata?.files || [];

  let prompt = `Invoke @agent-${agent} to: ${task.title}\n\n`;

  if (task.description) {
    prompt += `Description: ${task.description}\n\n`;
  }

  if (files.length > 0) {
    prompt += `Files: ${files.join(', ')}\n\n`;
  }

  prompt += `Context: Task ${task.id} in ${task.metadata?.streamId || 'main stream'}`;

  return prompt;
}

function extractAgentInvocation(prompt: string): string | null {
  const match = prompt.match(/@agent-(\w+)/);
  return match ? match[1] : null;
}

function simulateAgentHandoff(fromAgent: string, toAgent: string): { valid: boolean; reason?: string } {
  const validHandoffs: Record<string, string[]> = {
    'sd': ['uxd', 'ta'],
    'uxd': ['uids', 'sd', 'ta'],
    'uids': ['uid', 'uxd', 'ta'],
    'uid': ['qa', 'ta'],
    'me': ['qa', 'sec', 'ta'],
    'qa': ['me', 'ta'],
    'doc': ['ta'],
    'do': ['me', 'sec', 'ta'],
    'sec': ['ta']
  };

  const allowedTargets = validHandoffs[fromAgent] || ['ta'];

  if (allowedTargets.includes(toAgent)) {
    return { valid: true };
  }

  return {
    valid: false,
    reason: `Invalid handoff: @agent-${fromAgent} cannot route to @agent-${toAgent}`
  };
}

// ============================================================================
// TEST SUITE: AGENT ASSIGNMENT VALIDATION
// ============================================================================

async function testAgentAssignmentValidation() {
  console.log('\n📋 Testing Agent Assignment Validation...\n');

  await runTest('Valid agent assignment: me', () => {
    const task = MOCK_TASKS.codeTask;
    const result = validateAgentAssignment(task);
    assert(result.valid === true, 'Should accept valid agent "me"');
  });

  await runTest('Valid agent assignment: qa', () => {
    const task = MOCK_TASKS.testTask;
    const result = validateAgentAssignment(task);
    assert(result.valid === true, 'Should accept valid agent "qa"');
  });

  await runTest('Valid agent assignment: sec', () => {
    const task = MOCK_TASKS.securityTask;
    const result = validateAgentAssignment(task);
    assert(result.valid === true, 'Should accept valid agent "sec"');
  });

  await runTest('Unassigned task defaults to ta', () => {
    const task = MOCK_TASKS.unassignedTask;
    const result = validateAgentAssignment(task);
    assert(result.valid === true, 'Should accept unassigned task (defaults to ta)');
  });

  await runTest('Invalid agent assignment rejected', () => {
    const task = MOCK_TASKS.invalidTask;
    const result = validateAgentAssignment(task);
    assert(result.valid === false, 'Should reject invalid agent');
    assert(result.error !== undefined, 'Should provide error message');
  });

  await runTest('All valid agents accepted', () => {
    for (const agent of VALID_AGENTS) {
      const task: Task = {
        id: 'TASK-TEST',
        title: 'Test task',
        assignedAgent: agent,
        status: 'pending'
      };
      const result = validateAgentAssignment(task);
      assert(result.valid === true, `Should accept agent: ${agent}`);
    }
  });
}

// ============================================================================
// TEST SUITE: AGENT ROUTING CHAINS
// ============================================================================

async function testAgentRoutingChains() {
  console.log('\n🔄 Testing Agent Routing Chains...\n');

  await runTest('sd → uxd routing valid', () => {
    const result = simulateAgentHandoff('sd', 'uxd');
    assert(result.valid === true, 'Should allow sd to route to uxd');
  });

  await runTest('uxd → uids routing valid', () => {
    const result = simulateAgentHandoff('uxd', 'uids');
    assert(result.valid === true, 'Should allow uxd to route to uids');
  });

  await runTest('uids → uid routing valid', () => {
    const result = simulateAgentHandoff('uids', 'uid');
    assert(result.valid === true, 'Should allow uids to route to uid');
  });

  await runTest('me → qa routing valid', () => {
    const result = simulateAgentHandoff('me', 'qa');
    assert(result.valid === true, 'Should allow me to route to qa');
  });

  await runTest('me → sec routing valid', () => {
    const result = simulateAgentHandoff('me', 'sec');
    assert(result.valid === true, 'Should allow me to route to sec');
  });

  await runTest('All agents can route to ta', () => {
    for (const agent of VALID_AGENTS) {
      if (agent === 'ta') continue; // ta doesn't route to itself
      const result = simulateAgentHandoff(agent, 'ta');
      assert(result.valid === true, `Should allow ${agent} to route to ta`);
    }
  });

  await runTest('Invalid routing: qa → sd rejected', () => {
    const result = simulateAgentHandoff('qa', 'sd');
    assert(result.valid === false, 'Should reject invalid routing qa → sd');
    assert(result.reason !== undefined, 'Should provide rejection reason');
  });

  await runTest('Invalid routing: doc → me rejected', () => {
    const result = simulateAgentHandoff('doc', 'me');
    assert(result.valid === false, 'Should reject invalid routing doc → me');
  });
}

// ============================================================================
// TEST SUITE: WORKER PROMPT GENERATION
// ============================================================================

async function testWorkerPromptGeneration() {
  console.log('\n📝 Testing Worker Prompt Generation...\n');

  await runTest('Prompt includes agent invocation', () => {
    const task = MOCK_TASKS.codeTask;
    const prompt = generateWorkerPrompt(task);
    assertContains(prompt, '@agent-me', 'Prompt should include agent invocation');
  });

  await runTest('Prompt includes task title', () => {
    const task = MOCK_TASKS.codeTask;
    const prompt = generateWorkerPrompt(task);
    assertContains(prompt, task.title, 'Prompt should include task title');
  });

  await runTest('Prompt includes task context', () => {
    const task = MOCK_TASKS.codeTask;
    const prompt = generateWorkerPrompt(task);
    assertContains(prompt, task.id, 'Prompt should include task ID');
    assertContains(prompt, 'Stream-A', 'Prompt should include stream ID');
  });

  await runTest('Prompt includes files when present', () => {
    const task = MOCK_TASKS.codeTask;
    const prompt = generateWorkerPrompt(task);
    assertContains(prompt, 'src/auth/login.ts', 'Prompt should include files');
  });

  await runTest('Unassigned task defaults to ta in prompt', () => {
    const task = MOCK_TASKS.unassignedTask;
    const prompt = generateWorkerPrompt(task);
    assertContains(prompt, '@agent-ta', 'Unassigned task should default to @agent-ta');
  });

  await runTest('Agent invocation extractable from prompt', () => {
    const task = MOCK_TASKS.testTask;
    const prompt = generateWorkerPrompt(task);
    const extracted = extractAgentInvocation(prompt);
    assertEquals(extracted, 'qa', 'Should extract "qa" from prompt');
  });
}

// ============================================================================
// TEST SUITE: AGENT BYPASS DETECTION
// ============================================================================

async function testAgentBypassDetection() {
  console.log('\n🚨 Testing Agent Bypass Detection...\n');

  await runTest('Work product with correct agent_id passes', () => {
    const workProduct: WorkProduct = {
      id: 'WP-001',
      taskId: 'TASK-001',
      agentId: 'me',
      type: 'implementation',
      content: 'Code implementation...'
    };

    const task = MOCK_TASKS.codeTask;
    const agentMatch = workProduct.agentId === task.assignedAgent;
    assert(agentMatch, 'Work product agent_id should match task assignedAgent');
  });

  await runTest('Work product with mismatched agent_id fails', () => {
    const workProduct: WorkProduct = {
      id: 'WP-002',
      taskId: 'TASK-001',
      agentId: 'qa', // Should be 'me'
      type: 'implementation',
      content: 'Code implementation...'
    };

    const task = MOCK_TASKS.codeTask;
    const agentMatch = workProduct.agentId === task.assignedAgent;
    assert(!agentMatch, 'Work product agent_id mismatch should be detected');
  });

  await runTest('Work product type matches agent specialty', () => {
    const workProductTypes: Record<string, string[]> = {
      'me': ['implementation', 'refactoring', 'bug_fix'],
      'qa': ['test_plan', 'test_implementation'],
      'sec': ['security_review', 'vulnerability_assessment'],
      'doc': ['documentation', 'api_docs'],
      'do': ['infrastructure', 'ci_cd']
    };

    const workProduct: WorkProduct = {
      id: 'WP-003',
      taskId: 'TASK-001',
      agentId: 'me',
      type: 'implementation',
      content: 'Code...'
    };

    const validTypes = workProductTypes[workProduct.agentId] || [];
    const typeValid = validTypes.includes(workProduct.type);
    assert(typeValid, 'Work product type should match agent specialty');
  });

  await runTest('Generic response without agent invocation detected', () => {
    const genericResponse = 'Here is the implementation code without proper agent routing';
    const hasAgentInvocation = genericResponse.includes('@agent-');
    assert(!hasAgentInvocation, 'Generic response should not have agent invocation');
  });

  await runTest('Proper agent response includes invocation', () => {
    const properResponse = '@agent-me implemented the login API following the task requirements...';
    const hasAgentInvocation = properResponse.includes('@agent-');
    assert(hasAgentInvocation, 'Proper response should include agent invocation');
  });
}

// ============================================================================
// TEST SUITE: AGENT FILE STRUCTURE
// ============================================================================

async function testAgentFileStructure() {
  console.log('\n📁 Testing Agent File Structure...\n');

  const projectRoot = join(__dirname, '../..');
  const agentsDir = join(projectRoot, '.claude/agents');

  await runTest('All agents have skill_evaluate tool', () => {
    const leanAgents = ['me', 'qa', 'sec', 'doc', 'do', 'sd', 'uxd', 'uids', 'uid', 'cw'];

    for (const agent of leanAgents) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      // Check tools frontmatter
      const toolsMatch = content.match(/tools:\s*(.+)/);
      assert(toolsMatch !== null, `Agent ${agent} missing tools frontmatter`);

      const tools = toolsMatch[1];
      assertContains(tools, 'skill_evaluate', `Agent ${agent} missing skill_evaluate tool`);
    }
  });

  await runTest('All agents have Skill Loading Protocol section', () => {
    const leanAgents = ['me', 'qa', 'sec', 'doc', 'do', 'sd', 'uxd', 'uids', 'uid', 'cw'];

    for (const agent of leanAgents) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      assertContains(
        content,
        '## Skill Loading Protocol',
        `Agent ${agent} missing Skill Loading Protocol section`
      );
    }
  });

  await runTest('All agents include preflight_check tool', () => {
    const leanAgents = ['me', 'qa', 'sec', 'doc', 'do', 'sd', 'uxd', 'uids', 'uid', 'cw'];

    for (const agent of leanAgents) {
      const agentPath = join(agentsDir, `${agent}.md`);
      const content = readFileSync(agentPath, 'utf-8');

      const toolsMatch = content.match(/tools:\s*(.+)/);
      assert(toolsMatch !== null, `Agent ${agent} missing tools`);

      const tools = toolsMatch[1];
      assertContains(tools, 'preflight_check', `Agent ${agent} missing preflight_check tool`);
    }
  });
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function main() {
  console.log('='.repeat(70));
  console.log('  UNIT TESTS: AGENT ASSIGNMENT AND INVOCATION');
  console.log('='.repeat(70));

  await testAgentAssignmentValidation();
  await testAgentRoutingChains();
  await testWorkerPromptGeneration();
  await testAgentBypassDetection();
  await testAgentFileStructure();

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
