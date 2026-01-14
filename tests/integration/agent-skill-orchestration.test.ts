/**
 * Integration Tests: Agent + Skill + Orchestration
 *
 * End-to-end tests covering the complete workflow:
 * - PRD creation with agent assignments
 * - Task creation with stream metadata
 * - Agent invocation during orchestration
 * - Skill loading per agent
 * - Work product storage
 *
 * @see TEST_STRATEGY.md - Suite C and D
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
// MOCK DATA TYPES
// ============================================================================

interface PRD {
  id: string;
  title: string;
  description: string;
  acceptanceCriteria: string[];
  initiativeId?: string;
  metadata: {
    streams: StreamDefinition[];
  };
}

interface StreamDefinition {
  streamId: string;
  streamName: string;
  streamPhase: 'foundation' | 'parallel' | 'integration';
  dependencies: string[];
}

interface Task {
  id: string;
  prdId: string;
  title: string;
  description: string;
  assignedAgent: string;
  status: 'pending' | 'in_progress' | 'completed' | 'blocked';
  metadata: {
    streamId: string;
    streamName: string;
    streamDependencies: string[];
    files: string[];
  };
}

interface WorkProduct {
  id: string;
  taskId: string;
  agentId: string;
  type: string;
  content: string;
  skillsUsed?: string[];
}

interface WorkerPrompt {
  taskId: string;
  agentInvocation: string;
  context: string;
  skillHints?: string[];
}

// ============================================================================
// MOCK DATABASE
// ============================================================================

class MockTaskCopilot {
  private prds: Map<string, PRD> = new Map();
  private tasks: Map<string, Task> = new Map();
  private workProducts: Map<string, WorkProduct> = new Map();
  private currentInitiative: string | null = null;

  createPRD(prd: PRD): PRD {
    this.prds.set(prd.id, prd);
    return prd;
  }

  getPRD(id: string): PRD | undefined {
    return this.prds.get(id);
  }

  listPRDs(initiativeId?: string): PRD[] {
    const prds = Array.from(this.prds.values());
    if (initiativeId) {
      return prds.filter(p => p.initiativeId === initiativeId);
    }
    return prds;
  }

  createTask(task: Task): Task {
    this.tasks.set(task.id, task);
    return task;
  }

  getTask(id: string): Task | undefined {
    return this.tasks.get(id);
  }

  listTasks(filters?: { prdId?: string; status?: string; assignedAgent?: string }): Task[] {
    let tasks = Array.from(this.tasks.values());

    if (filters) {
      if (filters.prdId) {
        tasks = tasks.filter(t => t.prdId === filters.prdId);
      }
      if (filters.status) {
        tasks = tasks.filter(t => t.status === filters.status);
      }
      if (filters.assignedAgent) {
        tasks = tasks.filter(t => t.assignedAgent === filters.assignedAgent);
      }
    }

    return tasks;
  }

  listStreams(): StreamDefinition[] {
    const streams = new Map<string, StreamDefinition>();

    // Collect unique streams from tasks
    for (const task of this.tasks.values()) {
      if (task.metadata.streamId && !streams.has(task.metadata.streamId)) {
        streams.set(task.metadata.streamId, {
          streamId: task.metadata.streamId,
          streamName: task.metadata.streamName,
          streamPhase: this.inferStreamPhase(task.metadata.streamDependencies),
          dependencies: task.metadata.streamDependencies
        });
      }
    }

    return Array.from(streams.values());
  }

  private inferStreamPhase(dependencies: string[]): 'foundation' | 'parallel' | 'integration' {
    if (dependencies.length === 0) return 'foundation';
    if (dependencies.length === 1) return 'parallel';
    return 'integration';
  }

  storeWorkProduct(wp: WorkProduct): WorkProduct {
    this.workProducts.set(wp.id, wp);
    return wp;
  }

  getWorkProduct(id: string): WorkProduct | undefined {
    return this.workProducts.get(id);
  }

  listWorkProducts(taskId: string): WorkProduct[] {
    return Array.from(this.workProducts.values()).filter(wp => wp.taskId === taskId);
  }

  linkInitiative(initiativeId: string): void {
    this.currentInitiative = initiativeId;
  }

  getCurrentInitiative(): string | null {
    return this.currentInitiative;
  }

  validateStreamDependencies(): { valid: boolean; errors: string[] } {
    const streams = this.listStreams();
    const errors: string[] = [];

    // Check for cycles
    const visited = new Set<string>();
    const recursionStack = new Set<string>();

    const hasCycle = (streamId: string): boolean => {
      visited.add(streamId);
      recursionStack.add(streamId);

      const stream = streams.find(s => s.streamId === streamId);
      if (stream) {
        for (const dep of stream.dependencies) {
          if (!visited.has(dep)) {
            if (hasCycle(dep)) return true;
          } else if (recursionStack.has(dep)) {
            return true;
          }
        }
      }

      recursionStack.delete(streamId);
      return false;
    };

    for (const stream of streams) {
      visited.clear();
      recursionStack.clear();
      if (hasCycle(stream.streamId)) {
        errors.push(`Circular dependency detected involving: ${stream.streamId}`);
      }
    }

    // Check at least one foundation stream exists
    const foundationStreams = streams.filter(s => s.dependencies.length === 0);
    if (foundationStreams.length === 0 && streams.length > 0) {
      errors.push('No foundation stream found (all streams have dependencies)');
    }

    return { valid: errors.length === 0, errors };
  }

  reset(): void {
    this.prds.clear();
    this.tasks.clear();
    this.workProducts.clear();
    this.currentInitiative = null;
  }
}

// ============================================================================
// ORCHESTRATOR SIMULATOR
// ============================================================================

class MockOrchestrator {
  constructor(private taskCopilot: MockTaskCopilot) {}

  generateWorkerPrompt(task: Task): WorkerPrompt {
    const agent = task.assignedAgent || 'ta';
    const files = task.metadata.files || [];

    const context = [
      `Task: ${task.title}`,
      `Description: ${task.description}`,
      `Stream: ${task.metadata.streamName} (${task.metadata.streamId})`,
      files.length > 0 ? `Files: ${files.join(', ')}` : ''
    ].filter(Boolean).join('\n');

    // Generate skill hints based on files and description
    const skillHints = this.inferSkillHints(files, task.description);

    return {
      taskId: task.id,
      agentInvocation: `@agent-${agent}`,
      context,
      skillHints
    };
  }

  private inferSkillHints(files: string[], description: string): string[] {
    const hints: string[] = [];

    // File-based hints
    if (files.some(f => f.endsWith('.py'))) hints.push('python-idioms');
    if (files.some(f => f.match(/\.(test|spec)\./))) hints.push('testing-patterns');
    if (files.some(f => f.match(/\.(tsx|jsx)$/))) hints.push('react-patterns');
    if (files.some(f => f.match(/\.(ts|js)$/))) hints.push('javascript-patterns');

    // Description-based hints
    if (description.toLowerCase().includes('security')) hints.push('security-review');
    if (description.toLowerCase().includes('test')) hints.push('testing-patterns');
    if (description.toLowerCase().includes('auth')) hints.push('authentication-patterns');

    return [...new Set(hints)]; // Deduplicate
  }

  simulateAgentExecution(prompt: WorkerPrompt, task: Task): WorkProduct {
    // Simulate agent reading task and generating work product
    const content = `
Implementation for: ${task.title}

Agent: ${prompt.agentInvocation}
Context: ${prompt.context}

Work completed following task requirements.
Skills used: ${prompt.skillHints?.join(', ') || 'none'}

Co-Authored-By: ${prompt.agentInvocation.replace('@agent-', '')} <noreply@anthropic.com>
    `.trim();

    const workProduct: WorkProduct = {
      id: `WP-${task.id}`,
      taskId: task.id,
      agentId: task.assignedAgent,
      type: this.inferWorkProductType(task.assignedAgent),
      content,
      skillsUsed: prompt.skillHints
    };

    return this.taskCopilot.storeWorkProduct(workProduct);
  }

  private inferWorkProductType(agentId: string): string {
    const typeMap: Record<string, string> = {
      'me': 'implementation',
      'qa': 'test_plan',
      'sec': 'security_review',
      'doc': 'documentation',
      'do': 'infrastructure',
      'sd': 'service_design',
      'uxd': 'interaction_design',
      'uids': 'visual_design',
      'uid': 'ui_implementation',
      'cw': 'copy',
      'ta': 'architecture'
    };
    return typeMap[agentId] || 'other';
  }

  getStreamExecutionOrder(): string[][] {
    const streams = this.taskCopilot.listStreams();
    const layers: string[][] = [];
    const processed = new Set<string>();

    const remainingStreams = streams.length;

    while (processed.size < remainingStreams) {
      const currentLayer: string[] = [];

      for (const stream of streams) {
        if (processed.has(stream.streamId)) continue;

        // Check if all dependencies are processed
        const depsReady = stream.dependencies.every(dep => processed.has(dep));

        if (depsReady) {
          currentLayer.push(stream.streamId);
        }
      }

      if (currentLayer.length === 0) {
        // No progress made - likely circular dependency
        break;
      }

      // Mark streams as processed after collecting the layer
      for (const streamId of currentLayer) {
        processed.add(streamId);
      }

      layers.push(currentLayer);
    }

    return layers;
  }
}

// ============================================================================
// TEST SUITE: PRD AND TASK CREATION
// ============================================================================

async function testPRDTaskCreation() {
  console.log('\n📋 Testing PRD and Task Creation...\n');

  const taskCopilot = new MockTaskCopilot();

  await runTest('PRD created with stream metadata', () => {
    const prd: PRD = {
      id: 'PRD-001',
      title: 'User Authentication Feature',
      description: 'OAuth login with Google and GitHub',
      acceptanceCriteria: ['Users can log in', 'Session management', 'Tests pass'],
      initiativeId: 'INIT-001',
      metadata: {
        streams: [
          {
            streamId: 'Stream-A',
            streamName: 'Foundation',
            streamPhase: 'foundation',
            dependencies: []
          },
          {
            streamId: 'Stream-B',
            streamName: 'OAuth Integration',
            streamPhase: 'parallel',
            dependencies: ['Stream-A']
          },
          {
            streamId: 'Stream-C',
            streamName: 'Testing',
            streamPhase: 'parallel',
            dependencies: ['Stream-A']
          }
        ]
      }
    };

    const created = taskCopilot.createPRD(prd);
    assertEquals(created.id, 'PRD-001', 'PRD ID should match');
    assert(created.metadata.streams.length === 3, 'Should have 3 streams');
  });

  await runTest('Tasks created with correct agent assignments', () => {
    const tasks: Task[] = [
      {
        id: 'TASK-001',
        prdId: 'PRD-001',
        title: 'Create database schema',
        description: 'User and session tables',
        assignedAgent: 'me',
        status: 'pending',
        metadata: {
          streamId: 'Stream-A',
          streamName: 'Foundation',
          streamDependencies: [],
          files: ['src/models/user.ts', 'migrations/001_users.sql']
        }
      },
      {
        id: 'TASK-002',
        prdId: 'PRD-001',
        title: 'Implement OAuth providers',
        description: 'Google and GitHub OAuth',
        assignedAgent: 'me',
        status: 'pending',
        metadata: {
          streamId: 'Stream-B',
          streamName: 'OAuth Integration',
          streamDependencies: ['Stream-A'],
          files: ['src/auth/oauth.ts']
        }
      },
      {
        id: 'TASK-003',
        prdId: 'PRD-001',
        title: 'Write integration tests',
        description: 'Test OAuth flows',
        assignedAgent: 'qa',
        status: 'pending',
        metadata: {
          streamId: 'Stream-C',
          streamName: 'Testing',
          streamDependencies: ['Stream-A'],
          files: ['tests/auth.test.ts']
        }
      }
    ];

    for (const task of tasks) {
      taskCopilot.createTask(task);
    }

    const allTasks = taskCopilot.listTasks({ prdId: 'PRD-001' });
    assertEquals(allTasks.length, 3, 'Should have 3 tasks');

    const agentMeTasks = taskCopilot.listTasks({ assignedAgent: 'me' });
    assertEquals(agentMeTasks.length, 2, 'Should have 2 tasks assigned to @agent-me');

    const agentQaTasks = taskCopilot.listTasks({ assignedAgent: 'qa' });
    assertEquals(agentQaTasks.length, 1, 'Should have 1 task assigned to @agent-qa');
  });

  await runTest('Stream dependencies validated', () => {
    const validation = taskCopilot.validateStreamDependencies();
    assert(validation.valid === true, 'Stream dependencies should be valid');
    assertEquals(validation.errors.length, 0, 'Should have no validation errors');
  });

  await runTest('Foundation stream has no dependencies', () => {
    const streams = taskCopilot.listStreams();
    const foundationStream = streams.find(s => s.streamId === 'Stream-A');

    assert(foundationStream !== undefined, 'Foundation stream should exist');
    assertEquals(foundationStream.dependencies.length, 0, 'Foundation stream should have no dependencies');
  });

  await runTest('Parallel streams depend on foundation', () => {
    const streams = taskCopilot.listStreams();
    const streamB = streams.find(s => s.streamId === 'Stream-B');
    const streamC = streams.find(s => s.streamId === 'Stream-C');

    assert(streamB !== undefined, 'Stream-B should exist');
    assert(streamC !== undefined, 'Stream-C should exist');

    assertContains(
      JSON.stringify(streamB.dependencies),
      'Stream-A',
      'Stream-B should depend on Stream-A'
    );
    assertContains(
      JSON.stringify(streamC.dependencies),
      'Stream-A',
      'Stream-C should depend on Stream-A'
    );
  });

  taskCopilot.reset();
}

// ============================================================================
// TEST SUITE: AGENT INVOCATION
// ============================================================================

async function testAgentInvocation() {
  console.log('\n🎭 Testing Agent Invocation...\n');

  const taskCopilot = new MockTaskCopilot();
  const orchestrator = new MockOrchestrator(taskCopilot);

  // Set up test data
  const task: Task = {
    id: 'TASK-001',
    prdId: 'PRD-001',
    title: 'Implement OAuth login',
    description: 'Add Google OAuth support',
    assignedAgent: 'me',
    status: 'pending',
    metadata: {
      streamId: 'Stream-A',
      streamName: 'OAuth Integration',
      streamDependencies: [],
      files: ['src/auth/oauth.ts', 'tests/oauth.test.ts']
    }
  };

  taskCopilot.createTask(task);

  await runTest('Worker prompt includes agent invocation', () => {
    const prompt = orchestrator.generateWorkerPrompt(task);
    assertContains(prompt.agentInvocation, '@agent-me', 'Prompt should include @agent-me');
  });

  await runTest('Worker prompt includes task context', () => {
    const prompt = orchestrator.generateWorkerPrompt(task);
    assertContains(prompt.context, task.title, 'Context should include task title');
    assertContains(prompt.context, 'Stream-A', 'Context should include stream ID');
  });

  await runTest('Worker prompt includes skill hints', () => {
    const prompt = orchestrator.generateWorkerPrompt(task);
    assert(prompt.skillHints !== undefined, 'Should have skill hints');
    assert(prompt.skillHints.length > 0, 'Should have at least one skill hint');
  });

  await runTest('Agent execution creates work product', () => {
    const prompt = orchestrator.generateWorkerPrompt(task);
    const workProduct = orchestrator.simulateAgentExecution(prompt, task);

    assertEquals(workProduct.taskId, task.id, 'Work product should link to task');
    assertEquals(workProduct.agentId, 'me', 'Work product should have correct agent ID');
    assertContains(workProduct.content, '@agent-me', 'Work product should reference agent');
  });

  await runTest('Work product type matches agent specialty', () => {
    const prompt = orchestrator.generateWorkerPrompt(task);
    const workProduct = orchestrator.simulateAgentExecution(prompt, task);

    assertEquals(workProduct.type, 'implementation', '@agent-me should produce implementation type');
  });

  await runTest('Work product includes skills used', () => {
    const prompt = orchestrator.generateWorkerPrompt(task);
    const workProduct = orchestrator.simulateAgentExecution(prompt, task);

    assert(workProduct.skillsUsed !== undefined, 'Work product should track skills used');
    assertGreaterThan(workProduct.skillsUsed.length, 0, 'Should have used at least one skill');
  });

  taskCopilot.reset();
}

// ============================================================================
// TEST SUITE: ORCHESTRATION WORKFLOW
// ============================================================================

async function testOrchestrationWorkflow() {
  console.log('\n⚙️  Testing Orchestration Workflow...\n');

  const taskCopilot = new MockTaskCopilot();
  const orchestrator = new MockOrchestrator(taskCopilot);

  // Set up full workflow
  const prd: PRD = {
    id: 'PRD-001',
    title: 'Feature Implementation',
    description: 'Complete feature with tests and docs',
    acceptanceCriteria: ['Code complete', 'Tests pass', 'Docs written'],
    metadata: {
      streams: [
        {
          streamId: 'Stream-A',
          streamName: 'Foundation',
          streamPhase: 'foundation',
          dependencies: []
        },
        {
          streamId: 'Stream-B',
          streamName: 'Implementation',
          streamPhase: 'parallel',
          dependencies: ['Stream-A']
        },
        {
          streamId: 'Stream-C',
          streamName: 'Testing',
          streamPhase: 'parallel',
          dependencies: ['Stream-A']
        },
        {
          streamId: 'Stream-Z',
          streamName: 'Integration',
          streamPhase: 'integration',
          dependencies: ['Stream-B', 'Stream-C']
        }
      ]
    }
  };

  taskCopilot.createPRD(prd);

  const tasks: Task[] = [
    {
      id: 'TASK-A1',
      prdId: 'PRD-001',
      title: 'Set up types',
      description: 'TypeScript types',
      assignedAgent: 'me',
      status: 'pending',
      metadata: { streamId: 'Stream-A', streamName: 'Foundation', streamDependencies: [], files: ['src/types.ts'] }
    },
    {
      id: 'TASK-B1',
      prdId: 'PRD-001',
      title: 'Implement feature',
      description: 'Main logic',
      assignedAgent: 'me',
      status: 'pending',
      metadata: { streamId: 'Stream-B', streamName: 'Implementation', streamDependencies: ['Stream-A'], files: ['src/feature.ts'] }
    },
    {
      id: 'TASK-C1',
      prdId: 'PRD-001',
      title: 'Write tests',
      description: 'Unit tests',
      assignedAgent: 'qa',
      status: 'pending',
      metadata: { streamId: 'Stream-C', streamName: 'Testing', streamDependencies: ['Stream-A'], files: ['tests/feature.test.ts'] }
    },
    {
      id: 'TASK-Z1',
      prdId: 'PRD-001',
      title: 'Integration',
      description: 'Final integration',
      assignedAgent: 'me',
      status: 'pending',
      metadata: { streamId: 'Stream-Z', streamName: 'Integration', streamDependencies: ['Stream-B', 'Stream-C'], files: ['src/index.ts'] }
    }
  ];

  for (const task of tasks) {
    taskCopilot.createTask(task);
  }

  await runTest('Stream execution order correct', () => {
    const executionOrder = orchestrator.getStreamExecutionOrder();

    // Verify we have at least 3 layers
    assert(executionOrder.length >= 3, `Should have at least 3 layers, got ${executionOrder.length}`);

    // Layer 0 (foundation)
    assert(executionOrder[0] !== undefined, 'Layer 0 should exist');
    assert(executionOrder[0].includes('Stream-A'), 'Layer 0 should include Stream-A');

    // Layer 1 (parallel)
    assert(executionOrder[1] !== undefined, 'Layer 1 should exist');
    assert(executionOrder[1].includes('Stream-B'), 'Layer 1 should include Stream-B');
    assert(executionOrder[1].includes('Stream-C'), 'Layer 1 should include Stream-C');

    // Layer 2 (integration)
    assert(executionOrder[2] !== undefined, 'Layer 2 should exist');
    assert(executionOrder[2].includes('Stream-Z'), 'Layer 2 should include Stream-Z');
  });

  await runTest('All tasks have agent assignments', () => {
    const allTasks = taskCopilot.listTasks({ prdId: 'PRD-001' });

    for (const task of allTasks) {
      assert(task.assignedAgent !== undefined, `Task ${task.id} should have assignedAgent`);
      assert(task.assignedAgent.length > 0, `Task ${task.id} assignedAgent should not be empty`);
    }
  });

  await runTest('Worker prompts generated for all tasks', () => {
    const allTasks = taskCopilot.listTasks({ prdId: 'PRD-001' });

    for (const task of allTasks) {
      const prompt = orchestrator.generateWorkerPrompt(task);
      assertContains(prompt.agentInvocation, '@agent-', `Task ${task.id} should have agent invocation`);
    }
  });

  await runTest('All agents produce work products', () => {
    const allTasks = taskCopilot.listTasks({ prdId: 'PRD-001' });

    for (const task of allTasks) {
      const prompt = orchestrator.generateWorkerPrompt(task);
      const wp = orchestrator.simulateAgentExecution(prompt, task);

      assert(wp.agentId === task.assignedAgent, `Work product should match task agent`);
      assertContains(wp.content, 'Co-Authored-By', `Work product should have Co-Authored-By`);
    }
  });

  taskCopilot.reset();
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function main() {
  console.log('='.repeat(70));
  console.log('  INTEGRATION TESTS: AGENT + SKILL + ORCHESTRATION');
  console.log('='.repeat(70));

  await testPRDTaskCreation();
  await testAgentInvocation();
  await testOrchestrationWorkflow();

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
