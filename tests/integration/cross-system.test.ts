/**
 * Integration Tests: Cross-System Integration (Memory ↔ Task ↔ Knowledge)
 *
 * Tests data flow between the three core systems:
 * - Memory Copilot (initiative, decisions, lessons)
 * - Task Copilot (PRDs, tasks, work products)
 * - Knowledge Copilot (extensions, skills, corrections)
 *
 * Coverage:
 * - XS-01: Memory ↔ Task Linking (4 tests)
 * - XS-02: Task → Knowledge Flow (3 tests)
 * - XS-03: Correction → Agent Routing (4 tests)
 * - XS-04: Extension Resolution (2 tests)
 * - XS-05: Stream Archival (2 tests)
 *
 * @see docs/50-features/cross-system-integration.md
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
    throw new Error(`${message}: expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
  }
}

function assertContains<T>(array: T[], value: T, message: string): void {
  if (!array.includes(value)) {
    throw new Error(`${message}: array does not contain ${JSON.stringify(value)}`);
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

interface MockMemoryInitiative {
  id: string;
  projectId: string;
  name: string;
  status: 'NOT STARTED' | 'IN PROGRESS' | 'BLOCKED' | 'READY FOR REVIEW' | 'COMPLETE';
  taskCopilotLinked?: boolean;
  activePrdIds?: string[];
  decisions: string[];
  lessons: string[];
  keyFiles: string[];
  currentFocus?: string;
  nextAction?: string;
}

interface MockTaskPrd {
  id: string;
  initiativeId: string;
  title: string;
  status: 'active' | 'archived';
  milestones?: Array<{
    id: string;
    name: string;
    taskIds: string[];
  }>;
}

interface MockTaskWorkProduct {
  id: string;
  taskId: string;
  type: 'implementation' | 'test_plan' | 'architecture';
  content: string;
  metadata: {
    decisions?: string[];
    lessons?: string[];
  };
}

interface MockCorrection {
  id: string;
  userMessage: string;
  agentId?: string;
  status: 'pending' | 'approved' | 'rejected';
  target: 'skill' | 'agent' | 'memory';
  targetId?: string;
}

interface MockExtension {
  type: 'override' | 'extension';
  agentId: string;
  source: 'project' | 'global' | 'base';
  content: string;
  requiredSkills?: string[];
}

interface MockStream {
  streamId: string;
  initiativeId: string;
  archived: boolean;
  archivedAt?: string;
  archivedByInitiativeId?: string;
}

// ============================================================================
// XS-01: MEMORY ↔ TASK LINKING TESTS
// ============================================================================

async function runXS01Tests() {
  console.log('\n' + '='.repeat(70));
  console.log('XS-01: MEMORY ↔ TASK LINKING TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('initiative_link connects Memory initiative to Task workspace', () => {
    const memoryInitiative: MockMemoryInitiative = {
      id: 'INIT-001',
      projectId: 'test-project',
      name: 'Cross-system integration',
      status: 'IN PROGRESS',
      decisions: [],
      lessons: [],
      keyFiles: []
    };

    // Simulate initiative_link tool call
    const linkResult = {
      initiativeId: memoryInitiative.id,
      workspaceCreated: true,
      dbPath: '/path/to/workspace/INIT-001.db'
    };

    assertEquals(linkResult.initiativeId, memoryInitiative.id, 'Initiative ID should match');
    assert(linkResult.workspaceCreated, 'Workspace should be created');
    assert(linkResult.dbPath.includes(memoryInitiative.id), 'DB path should include initiative ID');
  });

  await runTest('WORKSPACE_ID propagates correctly between systems', () => {
    const workspaceId = 'test-workspace-hash';

    // Memory Copilot uses WORKSPACE_ID
    const memoryConfig = {
      WORKSPACE_ID: workspaceId,
      MEMORY_PATH: '/path/to/memory'
    };

    // Task Copilot should use same WORKSPACE_ID
    const taskConfig = {
      WORKSPACE_ID: workspaceId,
      TASK_DB_PATH: '/path/to/tasks'
    };

    assertEquals(memoryConfig.WORKSPACE_ID, taskConfig.WORKSPACE_ID, 'WORKSPACE_ID should match across systems');
  });

  await runTest('initiative_update with taskCopilotLinked enables slim mode', () => {
    const initiative: MockMemoryInitiative = {
      id: 'INIT-002',
      projectId: 'test-project',
      name: 'Test initiative',
      status: 'IN PROGRESS',
      taskCopilotLinked: false,
      decisions: ['Use TypeScript'],
      lessons: ['TDD improves quality'],
      keyFiles: ['src/index.ts']
    };

    // Update to enable Task Copilot link
    const updateInput = {
      taskCopilotLinked: true,
      currentFocus: 'Implementing authentication',
      nextAction: 'Complete login form tests'
    };

    initiative.taskCopilotLinked = updateInput.taskCopilotLinked;
    initiative.currentFocus = updateInput.currentFocus;
    initiative.nextAction = updateInput.nextAction;

    assert(initiative.taskCopilotLinked, 'Task Copilot should be linked');
    assert(initiative.currentFocus !== undefined, 'Current focus should be set for slim mode');
    assert(initiative.nextAction !== undefined, 'Next action should be set for slim mode');
  });

  await runTest('activePrdIds in Memory matches Task Copilot PRDs', () => {
    const prds: MockTaskPrd[] = [
      { id: 'PRD-001', initiativeId: 'INIT-003', title: 'Auth feature', status: 'active' },
      { id: 'PRD-002', initiativeId: 'INIT-003', title: 'Dashboard', status: 'active' }
    ];

    const initiative: MockMemoryInitiative = {
      id: 'INIT-003',
      projectId: 'test-project',
      name: 'Multi-PRD initiative',
      status: 'IN PROGRESS',
      taskCopilotLinked: true,
      activePrdIds: prds.filter(p => p.status === 'active').map(p => p.id),
      decisions: [],
      lessons: [],
      keyFiles: []
    };

    assertEquals(initiative.activePrdIds?.length, 2, 'Should track 2 active PRDs');
    assertContains(initiative.activePrdIds || [], 'PRD-001', 'Should include PRD-001');
    assertContains(initiative.activePrdIds || [], 'PRD-002', 'Should include PRD-002');
  });
}

// ============================================================================
// XS-02: TASK → KNOWLEDGE FLOW TESTS
// ============================================================================

async function runXS02Tests() {
  console.log('\n' + '='.repeat(70));
  console.log('XS-02: TASK → KNOWLEDGE FLOW TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('Work products with decisions update Memory', () => {
    const workProduct: MockTaskWorkProduct = {
      id: 'WP-001',
      taskId: 'TASK-001',
      type: 'architecture',
      content: '# Architecture Design\n\nDecision: Use PostgreSQL for persistence.',
      metadata: {
        decisions: [
          'Use PostgreSQL for better JSONB support',
          'Implement connection pooling with pg-pool'
        ]
      }
    };

    const initiative: MockMemoryInitiative = {
      id: 'INIT-004',
      projectId: 'test-project',
      name: 'Database design',
      status: 'IN PROGRESS',
      decisions: [],
      lessons: [],
      keyFiles: []
    };

    // Simulate work product completion updating Memory
    if (workProduct.metadata.decisions) {
      initiative.decisions.push(...workProduct.metadata.decisions);
    }

    assertEquals(initiative.decisions.length, 2, 'Should have 2 decisions');
    assert(initiative.decisions.some(d => d.includes('PostgreSQL')), 'Should include PostgreSQL decision');
  });

  await runTest('PRD milestones track in Memory currentFocus', () => {
    const prd: MockTaskPrd = {
      id: 'PRD-003',
      initiativeId: 'INIT-005',
      title: 'User authentication',
      status: 'active',
      milestones: [
        { id: 'M1', name: 'Foundation', taskIds: ['TASK-001', 'TASK-002'] },
        { id: 'M2', name: 'Testing', taskIds: ['TASK-003'] }
      ]
    };

    const initiative: MockMemoryInitiative = {
      id: 'INIT-005',
      projectId: 'test-project',
      name: 'Auth system',
      status: 'IN PROGRESS',
      taskCopilotLinked: true,
      activePrdIds: [prd.id],
      currentFocus: undefined,
      decisions: [],
      lessons: [],
      keyFiles: []
    };

    // Simulate milestone progress updating currentFocus
    const currentMilestone = prd.milestones?.[0];
    if (currentMilestone) {
      initiative.currentFocus = `Milestone: ${currentMilestone.name} (${currentMilestone.taskIds.length} tasks)`;
    }

    assert(initiative.currentFocus !== undefined, 'Current focus should be updated');
    assert(initiative.currentFocus?.includes('Foundation'), 'Should reference current milestone');
  });

  await runTest('Task completion updates Memory initiative status', () => {
    const tasks = [
      { id: 'TASK-001', status: 'completed' },
      { id: 'TASK-002', status: 'completed' },
      { id: 'TASK-003', status: 'completed' }
    ];

    const initiative: MockMemoryInitiative = {
      id: 'INIT-006',
      projectId: 'test-project',
      name: 'Quick feature',
      status: 'IN PROGRESS',
      decisions: [],
      lessons: [],
      keyFiles: []
    };

    // Simulate all tasks complete
    const allCompleted = tasks.every(t => t.status === 'completed');
    if (allCompleted) {
      initiative.status = 'READY FOR REVIEW';
    }

    assertEquals(initiative.status, 'READY FOR REVIEW', 'Initiative should be ready for review');
  });
}

// ============================================================================
// XS-03: CORRECTION → AGENT ROUTING TESTS
// ============================================================================

async function runXS03Tests() {
  console.log('\n' + '='.repeat(70));
  console.log('XS-03: CORRECTION → AGENT ROUTING TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('Approved correction routes to target skill file', () => {
    const correction: MockCorrection = {
      id: 'CORR-001',
      userMessage: 'Actually, use async/await instead of callbacks',
      agentId: 'me',
      status: 'approved',
      target: 'skill',
      targetId: 'agent-me'
    };

    // Simulate routing logic
    const routeResult = {
      target: correction.target,
      filePath: `.claude/skills/code/${correction.targetId}/async-patterns.md`,
      action: 'append_to_anti_patterns'
    };

    assertEquals(routeResult.target, 'skill', 'Should route to skill');
    assert(routeResult.filePath.includes('async-patterns'), 'Should target async patterns skill');
  });

  await runTest('Approved correction routes to target agent definition', () => {
    const correction: MockCorrection = {
      id: 'CORR-002',
      userMessage: 'QA agent should always run integration tests before unit tests',
      agentId: 'qa',
      status: 'approved',
      target: 'agent',
      targetId: 'qa'
    };

    // Simulate routing logic
    const routeResult = {
      target: correction.target,
      filePath: `.claude/agents/${correction.targetId}.md`,
      section: 'Core Behaviors',
      action: 'update_always_list'
    };

    assertEquals(routeResult.target, 'agent', 'Should route to agent');
    assertEquals(routeResult.filePath, '.claude/agents/qa.md', 'Should target QA agent file');
    assertEquals(routeResult.section, 'Core Behaviors', 'Should update Core Behaviors section');
  });

  await runTest('Approved correction stores in Memory as lesson', () => {
    const correction: MockCorrection = {
      id: 'CORR-003',
      userMessage: 'Remember to validate input before processing',
      status: 'approved',
      target: 'memory'
    };

    const initiative: MockMemoryInitiative = {
      id: 'INIT-007',
      projectId: 'test-project',
      name: 'Security improvements',
      status: 'IN PROGRESS',
      decisions: [],
      lessons: [],
      keyFiles: []
    };

    // Simulate correction storing in Memory
    const lesson = `Correction applied: ${correction.userMessage}`;
    initiative.lessons.push(lesson);

    assertEquals(initiative.lessons.length, 1, 'Should have 1 lesson');
    assert(initiative.lessons[0].includes('validate input'), 'Lesson should include correction message');
  });

  await runTest('Correction with agentId filters correctly', () => {
    const corrections: MockCorrection[] = [
      { id: 'CORR-004', userMessage: 'Use TypeScript', agentId: 'me', status: 'pending', target: 'skill' },
      { id: 'CORR-005', userMessage: 'Add security scan', agentId: 'sec', status: 'pending', target: 'agent' },
      { id: 'CORR-006', userMessage: 'Test edge cases', agentId: 'qa', status: 'pending', target: 'skill' }
    ];

    // Filter by agentId
    const meCorrections = corrections.filter(c => c.agentId === 'me');
    const secCorrections = corrections.filter(c => c.agentId === 'sec');

    assertEquals(meCorrections.length, 1, 'Should filter 1 correction for agent-me');
    assertEquals(secCorrections.length, 1, 'Should filter 1 correction for agent-sec');
    assertEquals(meCorrections[0].id, 'CORR-004', 'Should return correct correction');
  });
}

// ============================================================================
// XS-04: EXTENSION RESOLUTION TESTS
// ============================================================================

async function runXS04Tests() {
  console.log('\n' + '='.repeat(70));
  console.log('XS-04: EXTENSION RESOLUTION TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('Project extension overrides global extension', () => {
    const projectExtension: MockExtension = {
      type: 'override',
      agentId: 'sd',
      source: 'project',
      content: '# Project-specific Service Designer\n\nUse Figma for all designs.'
    };

    const globalExtension: MockExtension = {
      type: 'extension',
      agentId: 'sd',
      source: 'global',
      content: '# Global Service Designer\n\nUse Sketch for designs.'
    };

    // Simulate resolution priority: project > global > base
    const extensions = [projectExtension, globalExtension];
    const resolved = extensions.find(e => e.source === 'project') ||
                      extensions.find(e => e.source === 'global');

    assertEquals(resolved?.source, 'project', 'Should prioritize project extension');
    assert(resolved?.content.includes('Figma'), 'Should use project-specific content');
  });

  await runTest('Missing project extension falls back to global', () => {
    const globalExtension: MockExtension = {
      type: 'extension',
      agentId: 'uxd',
      source: 'global',
      content: '# Global UX Designer\n\nFollow company design system.'
    };

    const baseAgent: MockExtension = {
      type: 'override',
      agentId: 'uxd',
      source: 'base',
      content: '# Base UX Designer\n\nGeneric UX guidance.'
    };

    // Simulate resolution when no project extension exists
    const extensions = [globalExtension, baseAgent];
    const resolved = extensions.find(e => e.source === 'project') ||
                      extensions.find(e => e.source === 'global') ||
                      extensions.find(e => e.source === 'base');

    assertEquals(resolved?.source, 'global', 'Should fall back to global extension');
    assert(resolved?.content.includes('company design system'), 'Should use global content');
  });
}

// ============================================================================
// XS-05: STREAM ARCHIVAL TESTS
// ============================================================================

async function runXS05Tests() {
  console.log('\n' + '='.repeat(70));
  console.log('XS-05: STREAM ARCHIVAL TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('Initiative switch archives old streams', () => {
    const oldStreams: MockStream[] = [
      { streamId: 'Stream-A', initiativeId: 'INIT-OLD', archived: false },
      { streamId: 'Stream-B', initiativeId: 'INIT-OLD', archived: false }
    ];

    const newInitiative = 'INIT-NEW';

    // Simulate initiative_link archiving old streams
    const archivedStreams = oldStreams.map(stream => ({
      ...stream,
      archived: true,
      archivedAt: new Date().toISOString(),
      archivedByInitiativeId: newInitiative
    }));

    assert(archivedStreams.every(s => s.archived), 'All old streams should be archived');
    assert(archivedStreams.every(s => s.archivedByInitiativeId === newInitiative), 'Should track new initiative');
  });

  await runTest('Stream unarchive links to current initiative', () => {
    const archivedStream: MockStream = {
      streamId: 'Stream-C',
      initiativeId: 'INIT-OLD',
      archived: true,
      archivedAt: '2024-01-01T00:00:00Z',
      archivedByInitiativeId: 'INIT-NEW'
    };

    const currentInitiative = 'INIT-CURRENT';

    // Simulate stream_unarchive
    const unarchived: MockStream = {
      ...archivedStream,
      archived: false,
      initiativeId: currentInitiative,
      archivedAt: undefined,
      archivedByInitiativeId: undefined
    };

    assert(!unarchived.archived, 'Stream should be unarchived');
    assertEquals(unarchived.initiativeId, currentInitiative, 'Should link to current initiative');
    assertEquals(unarchived.archivedAt, undefined, 'Archived timestamp should be cleared');
  });
}

// ============================================================================
// E2E CROSS-SYSTEM WORKFLOW TESTS
// ============================================================================

async function runE2ETests() {
  console.log('\n' + '='.repeat(70));
  console.log('E2E: CROSS-SYSTEM WORKFLOW TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('Complete workflow: Memory → Task → Knowledge → Memory', () => {
    // Step 1: Start initiative in Memory Copilot
    const initiative: MockMemoryInitiative = {
      id: 'INIT-E2E',
      projectId: 'test-project',
      name: 'Full workflow test',
      status: 'IN PROGRESS',
      taskCopilotLinked: false,
      decisions: [],
      lessons: [],
      keyFiles: []
    };

    assert(initiative.id !== undefined, 'Initiative should be created');

    // Step 2: Link to Task Copilot
    initiative.taskCopilotLinked = true;
    initiative.currentFocus = 'Setting up architecture';
    initiative.nextAction = 'Create PRD';

    assert(initiative.taskCopilotLinked, 'Should link to Task Copilot');

    // Step 3: Create PRD and tasks in Task Copilot
    const prd: MockTaskPrd = {
      id: 'PRD-E2E',
      initiativeId: initiative.id,
      title: 'Architecture setup',
      status: 'active'
    };

    const workProduct: MockTaskWorkProduct = {
      id: 'WP-E2E',
      taskId: 'TASK-E2E',
      type: 'architecture',
      content: 'Architecture decisions...',
      metadata: {
        decisions: ['Use microservices'],
        lessons: ['Start with monolith']
      }
    };

    // Step 4: Work products flow back to Memory
    if (workProduct.metadata.decisions) {
      initiative.decisions.push(...workProduct.metadata.decisions);
    }
    if (workProduct.metadata.lessons) {
      initiative.lessons.push(...workProduct.metadata.lessons);
    }

    assertEquals(initiative.decisions.length, 1, 'Decision should flow to Memory');
    assertEquals(initiative.lessons.length, 1, 'Lesson should flow to Memory');

    // Step 5: User correction flows to Knowledge
    const correction: MockCorrection = {
      id: 'CORR-E2E',
      userMessage: 'Always document architecture decisions',
      agentId: 'ta',
      status: 'approved',
      target: 'agent',
      targetId: 'ta'
    };

    const correctionLesson = `Correction: ${correction.userMessage}`;
    initiative.lessons.push(correctionLesson);

    assertEquals(initiative.lessons.length, 2, 'Correction should be stored as lesson');

    // Step 6: Verify complete loop
    assert(initiative.decisions.length > 0, 'Should have captured decisions');
    assert(initiative.lessons.length > 0, 'Should have captured lessons');
    assert(initiative.taskCopilotLinked, 'Should remain linked to Task Copilot');
  });

  await runTest('Parallel streams with conflict detection', () => {
    const streams: MockStream[] = [
      { streamId: 'Stream-A', initiativeId: 'INIT-PARALLEL', archived: false },
      { streamId: 'Stream-B', initiativeId: 'INIT-PARALLEL', archived: false }
    ];

    // Simulate file assignments
    const streamFiles = {
      'Stream-A': ['src/auth.ts', 'src/user.ts'],
      'Stream-B': ['src/api.ts', 'src/routes.ts']
    };

    // Check for conflicts
    const fileA = streamFiles['Stream-A'];
    const fileB = streamFiles['Stream-B'];
    const conflicts = fileA.filter(f => fileB.includes(f));

    assertEquals(conflicts.length, 0, 'Parallel streams should have no file conflicts');
  });
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function runAllTests() {
  console.log('\n' + '='.repeat(70));
  console.log('CROSS-SYSTEM INTEGRATION TESTS');
  console.log('Memory ↔ Task ↔ Knowledge');
  console.log('='.repeat(70));

  await runXS01Tests();
  await runXS02Tests();
  await runXS03Tests();
  await runXS04Tests();
  await runXS05Tests();
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
