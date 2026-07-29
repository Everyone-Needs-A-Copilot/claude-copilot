/**
 * Integration Tests: Specification Workflow
 *
 * Tests the "Work Product → TA Review" specification workflow:
 * - Domain agents create specifications
 * - TA discovers specifications for PRD
 * - TA creates tasks with specification linkage
 * - Implementation agents read source specifications
 * - Multiple specifications consolidated
 * - Fallback case when no specifications exist
 *
 * @see docs/50-features/specification-workflow.md
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

function assertContains(text: string, substring: string, message: string): void {
  if (!text.includes(substring)) {
    throw new Error(`${message}: expected "${text}" to contain "${substring}"`);
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
// MOCK DATABASE CLIENT
// ============================================================================

interface MockPrd {
  id: string;
  initiative_id: string;
  title: string;
  description: string | null;
  content: string;
  metadata: string;
  status: string;
  created_at: string;
  updated_at: string;
}

interface MockTask {
  id: string;
  prd_id: string | null;
  parent_id: string | null;
  title: string;
  description: string | null;
  assigned_agent: string | null;
  status: string;
  blocked_reason: string | null;
  notes: string | null;
  metadata: string;
  created_at: string;
  updated_at: string;
}

interface MockWorkProduct {
  id: string;
  task_id: string;
  type: string;
  title: string;
  content: string;
  metadata: string;
  created_at: string;
  confidence: number | null;
}

class MockDatabaseClient {
  private prds: Map<string, MockPrd> = new Map();
  private tasks: Map<string, MockTask> = new Map();
  private workProducts: Map<string, MockWorkProduct> = new Map();
  private currentInitiative = { id: 'INIT-test', title: 'Test Initiative' };

  getCurrentInitiative() {
    return this.currentInitiative;
  }

  insertPrd(prd: MockPrd) {
    this.prds.set(prd.id, prd);
  }

  getPrd(id: string) {
    return this.prds.get(id) || null;
  }

  insertTask(task: MockTask) {
    this.tasks.set(task.id, task);
  }

  getTask(id: string) {
    return this.tasks.get(id) || null;
  }

  listTasks(filters: { prdId?: string; parentId?: string; status?: string; assignedAgent?: string }) {
    return Array.from(this.tasks.values()).filter(t => {
      if (filters.prdId && t.prd_id !== filters.prdId) return false;
      if (filters.parentId !== undefined && t.parent_id !== filters.parentId) return false;
      if (filters.status && t.status !== filters.status) return false;
      if (filters.assignedAgent && t.assigned_agent !== filters.assignedAgent) return false;
      return true;
    });
  }

  insertWorkProduct(wp: MockWorkProduct) {
    this.workProducts.set(wp.id, wp);
  }

  getWorkProduct(id: string) {
    return this.workProducts.get(id) || null;
  }

  listWorkProducts(taskId: string) {
    return Array.from(this.workProducts.values()).filter(wp => wp.task_id === taskId);
  }

  listWorkProductsByType(type: string) {
    return Array.from(this.workProducts.values()).filter(wp => wp.type === type);
  }

  reset() {
    this.prds.clear();
    this.tasks.clear();
    this.workProducts.clear();
  }
}

// ============================================================================
// MOCK TOOL IMPLEMENTATIONS
// ============================================================================

let idCounter = 0;
function generateId(prefix: string): string {
  return `${prefix}-${Date.now()}-${idCounter++}`;
}

async function prdCreate(db: MockDatabaseClient, input: {
  title: string;
  description?: string;
  content: string;
  metadata?: Record<string, unknown>;
}) {
  const now = new Date().toISOString();
  const id = generateId('PRD');
  const initiative = db.getCurrentInitiative();

  const prd: MockPrd = {
    id,
    initiative_id: initiative.id,
    title: input.title,
    description: input.description || null,
    content: input.content,
    metadata: JSON.stringify(input.metadata || {}),
    status: 'active',
    created_at: now,
    updated_at: now
  };

  db.insertPrd(prd);

  return {
    id,
    initiativeId: initiative.id,
    createdAt: now
  };
}

async function taskCreate(db: MockDatabaseClient, input: {
  title: string;
  description?: string;
  prdId?: string;
  parentId?: string;
  assignedAgent?: string;
  metadata?: Record<string, unknown>;
  notes?: string;
}) {
  const now = new Date().toISOString();
  const id = generateId('TASK');

  const task: MockTask = {
    id,
    prd_id: input.prdId || null,
    parent_id: input.parentId || null,
    title: input.title,
    description: input.description || null,
    assigned_agent: input.assignedAgent || null,
    status: 'pending',
    blocked_reason: null,
    notes: input.notes || null,
    metadata: JSON.stringify(input.metadata || {}),
    created_at: now,
    updated_at: now
  };

  db.insertTask(task);

  return {
    id,
    prdId: input.prdId,
    parentId: input.parentId,
    status: 'pending' as const,
    createdAt: now
  };
}

function taskGet(db: MockDatabaseClient, input: {
  id: string;
  includeSubtasks?: boolean;
  includeWorkProducts?: boolean;
}) {
  const task = db.getTask(input.id);
  if (!task) return null;

  return {
    id: task.id,
    prdId: task.prd_id || undefined,
    parentId: task.parent_id || undefined,
    title: task.title,
    description: task.description || undefined,
    assignedAgent: task.assigned_agent || undefined,
    status: task.status,
    notes: task.notes || undefined,
    metadata: JSON.parse(task.metadata),
    createdAt: task.created_at,
    updatedAt: task.updated_at
  };
}

async function workProductStore(db: MockDatabaseClient, input: {
  taskId: string;
  type: string;
  title: string;
  content: string;
  metadata?: Record<string, unknown>;
  confidence?: number;
}) {
  const now = new Date().toISOString();
  const id = generateId('WP');

  if (input.confidence !== undefined && (input.confidence < 0 || input.confidence > 1)) {
    throw new Error('Confidence must be between 0 and 1');
  }

  const wp: MockWorkProduct = {
    id,
    task_id: input.taskId,
    type: input.type,
    title: input.title,
    content: input.content,
    metadata: JSON.stringify(input.metadata || {}),
    created_at: now,
    confidence: input.confidence ?? null
  };

  db.insertWorkProduct(wp);

  return {
    id,
    taskId: input.taskId,
    summary: input.content.substring(0, 300),
    wordCount: input.content.split(/\s+/).filter(w => w.length > 0).length,
    createdAt: now
  };
}

function workProductGet(db: MockDatabaseClient, input: { id: string }) {
  const wp = db.getWorkProduct(input.id);
  if (!wp) return null;

  return {
    id: wp.id,
    taskId: wp.task_id,
    type: wp.type,
    title: wp.title,
    content: wp.content,
    metadata: JSON.parse(wp.metadata),
    createdAt: wp.created_at,
    confidence: wp.confidence
  };
}

function workProductList(db: MockDatabaseClient, input: { taskId?: string; type?: string }) {
  let workProducts: MockWorkProduct[];

  if (input.taskId) {
    workProducts = db.listWorkProducts(input.taskId);
  } else if (input.type) {
    workProducts = db.listWorkProductsByType(input.type);
  } else {
    return [];
  }

  return workProducts.map(wp => ({
    id: wp.id,
    taskId: wp.task_id,
    type: wp.type,
    title: wp.title,
    summary: wp.content.substring(0, 300),
    wordCount: wp.content.split(/\s+/).filter(w => w.length > 0).length,
    createdAt: wp.created_at,
    confidence: wp.confidence
  }));
}

// ============================================================================
// TEST SUITE: DOMAIN AGENT CREATES SPECIFICATION
// ============================================================================

async function testDomainAgentCreatesSpecification(db: MockDatabaseClient) {
  console.log('\n' + '='.repeat(70));
  console.log('TEST SUITE: Domain Agent Creates Specification');
  console.log('='.repeat(70) + '\n');

  await runTest('Domain agent stores work product with type specification', async () => {
    db.reset();

    // Set up PRD and task
    const prd = await prdCreate(db, {
      title: 'User Profile Feature',
      content: 'Allow users to edit their profile information'
    });

    const task = await taskCreate(db, {
      title: 'Design user profile interaction',
      prdId: prd.id,
      assignedAgent: 'uxd'
    });

    // UX Designer creates specification
    const wp = await workProductStore(db, {
      taskId: task.id,
      type: 'specification',
      title: 'User Profile UX Specification',
      content: `# User Profile UX Specification

## Interaction Flow
1. User clicks "Edit Profile" button
2. Form appears with current data pre-filled
3. User edits fields
4. User clicks "Save" or "Cancel"

## Required Sections
- Profile photo upload
- Name fields
- Bio text area
- Save/Cancel buttons

## Acceptance Criteria
- Form validates on blur
- Save button disabled until changes made
- Cancel confirms if unsaved changes exist`
    });

    assert(wp.id.startsWith('WP-'), 'Work product ID should have WP- prefix');
    assertEquals(wp.taskId, task.id, 'Should link to task');
    assert(wp.wordCount > 0, 'Should calculate word count');

    // Verify specification was saved correctly
    const retrieved = workProductGet(db, { id: wp.id });
    assert(retrieved !== null, 'Should retrieve work product');
    assertEquals(retrieved.type, 'specification', 'Type should be specification');
    assertContains(retrieved.content, 'Interaction Flow', 'Should contain interaction flow');
    assertContains(retrieved.content, 'Acceptance Criteria', 'Should contain acceptance criteria');
  });

  await runTest('Specification includes required sections', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Dashboard UI',
      content: 'Create dashboard UI'
    });

    const task = await taskCreate(db, {
      title: 'Design dashboard layout',
      prdId: prd.id,
      assignedAgent: 'uids'
    });

    // UI Designer creates visual specification
    const wp = await workProductStore(db, {
      taskId: task.id,
      type: 'specification',
      title: 'Dashboard Visual Design Specification',
      content: `# Dashboard Visual Design Specification

## Visual Layout
- Grid: 12-column responsive
- Breakpoints: mobile (320px), tablet (768px), desktop (1024px)

## Color Palette
- Primary: #2563EB
- Secondary: #10B981
- Background: #F9FAFB

## Typography
- Headings: Inter Bold
- Body: Inter Regular

## Component Specifications
- Card shadow: 0 1px 3px rgba(0,0,0,0.1)
- Border radius: 8px
- Spacing unit: 8px

## Acceptance Criteria
- Passes contrast ratio WCAG AA
- Mobile-first responsive
- Dark mode support`
    });

    const retrieved = workProductGet(db, { id: wp.id });
    assert(retrieved !== null, 'Specification should exist');
    assertContains(retrieved.content, 'Visual Layout', 'Should have visual layout section');
    assertContains(retrieved.content, 'Color Palette', 'Should have color palette section');
    assertContains(retrieved.content, 'Component Specifications', 'Should have component specs');
    assertContains(retrieved.content, 'Acceptance Criteria', 'Should have acceptance criteria');
  });
}

// ============================================================================
// TEST SUITE: TA DISCOVERS SPECIFICATIONS FOR PRD
// ============================================================================

async function testTADiscoversSpecifications(db: MockDatabaseClient) {
  console.log('\n' + '='.repeat(70));
  console.log('TEST SUITE: TA Discovers Specifications for PRD');
  console.log('='.repeat(70) + '\n');

  await runTest('TA finds all specifications for a PRD', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'E-commerce Checkout',
      content: 'Complete checkout flow'
    });

    // Create specification tasks
    const uxTask = await taskCreate(db, {
      title: 'UX specification for checkout',
      prdId: prd.id,
      assignedAgent: 'uxd'
    });

    const uiTask = await taskCreate(db, {
      title: 'UI specification for checkout',
      prdId: prd.id,
      assignedAgent: 'uids'
    });

    const copyTask = await taskCreate(db, {
      title: 'Copy specification for checkout',
      prdId: prd.id,
      assignedAgent: 'cw'
    });

    // Domain agents create specifications
    await workProductStore(db, {
      taskId: uxTask.id,
      type: 'specification',
      title: 'Checkout UX Specification',
      content: 'UX interaction patterns and flows'
    });

    await workProductStore(db, {
      taskId: uiTask.id,
      type: 'specification',
      title: 'Checkout UI Specification',
      content: 'Visual design and component specs'
    });

    await workProductStore(db, {
      taskId: copyTask.id,
      type: 'specification',
      title: 'Checkout Copy Specification',
      content: 'Microcopy and error messages'
    });

    // TA discovers all specifications
    const specifications = workProductList(db, { type: 'specification' });

    assertEquals(specifications.length, 3, 'Should find 3 specifications');

    const titles = specifications.map(s => s.title);
    assert(titles.some(t => t.includes('UX')), 'Should include UX specification');
    assert(titles.some(t => t.includes('UI')), 'Should include UI specification');
    assert(titles.some(t => t.includes('Copy')), 'Should include Copy specification');
  });

  await runTest('TA filters specifications by type correctly', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Test Feature',
      content: 'Test content'
    });

    const task1 = await taskCreate(db, {
      title: 'Task 1',
      prdId: prd.id,
      assignedAgent: 'uxd'
    });

    const task2 = await taskCreate(db, {
      title: 'Task 2',
      prdId: prd.id,
      assignedAgent: 'me'
    });

    // Create one specification and one implementation
    await workProductStore(db, {
      taskId: task1.id,
      type: 'specification',
      title: 'UX Spec',
      content: 'Specification content'
    });

    await workProductStore(db, {
      taskId: task2.id,
      type: 'implementation',
      title: 'Code Implementation',
      content: 'Code content'
    });

    // Query only specifications
    const specifications = workProductList(db, { type: 'specification' });

    assertEquals(specifications.length, 1, 'Should find only 1 specification');
    assertEquals(specifications[0].type, 'specification', 'Type should be specification');
    assertContains(specifications[0].title, 'UX Spec', 'Should be the UX specification');
  });
}

// ============================================================================
// TEST SUITE: TA CREATES TASKS WITH SPECIFICATION LINKAGE
// ============================================================================

async function testTACreatesSpecInformedTasks(db: MockDatabaseClient) {
  console.log('\n' + '='.repeat(70));
  console.log('TEST SUITE: TA Creates Spec-Informed Tasks');
  console.log('='.repeat(70) + '\n');

  await runTest('TA creates task with specification linkage', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Payment Integration',
      content: 'Integrate Stripe payment'
    });

    const specTask = await taskCreate(db, {
      title: 'Design payment flow',
      prdId: prd.id,
      assignedAgent: 'uxd'
    });

    const spec = await workProductStore(db, {
      taskId: specTask.id,
      type: 'specification',
      title: 'Payment Flow Specification',
      content: `# Payment Flow Specification

## User Journey
1. User adds items to cart
2. User proceeds to checkout
3. User enters payment details
4. System processes payment
5. User receives confirmation

## Acceptance Criteria
- Support credit cards and PayPal
- Display loading state during processing
- Show error messages for failed payments
- Send confirmation email on success`
    });

    // TA creates implementation task with specification reference
    const implTask = await taskCreate(db, {
      title: 'Implement payment endpoint',
      description: 'Implement Stripe payment endpoint',
      prdId: prd.id,
      assignedAgent: 'me',
      metadata: {
        sourceSpecifications: [spec.id]
      }
    });

    const retrieved = taskGet(db, { id: implTask.id });
    assert(retrieved !== null, 'Task should exist');
    assert(retrieved.metadata.sourceSpecifications, 'Should have sourceSpecifications in metadata');
    assertEquals(retrieved.metadata.sourceSpecifications.length, 1, 'Should reference 1 specification');
    assertEquals(retrieved.metadata.sourceSpecifications[0], spec.id, 'Should reference correct specification');
  });

  await runTest('Task description includes spec-derived acceptance criteria', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Search Feature',
      content: 'Add search functionality'
    });

    const specTask = await taskCreate(db, {
      title: 'Design search UX',
      prdId: prd.id,
      assignedAgent: 'uxd'
    });

    const spec = await workProductStore(db, {
      taskId: specTask.id,
      type: 'specification',
      title: 'Search UX Specification',
      content: `# Search UX Specification

## Acceptance Criteria
- Search as user types (debounced 300ms)
- Show results in dropdown
- Highlight matching text
- Show "No results" message when empty`
    });

    // TA creates task with acceptance criteria from spec
    const implTask = await taskCreate(db, {
      title: 'Implement search API',
      description: `Implement search endpoint with the following acceptance criteria:
- Search as user types (debounced 300ms)
- Show results in dropdown
- Highlight matching text
- Show "No results" message when empty`,
      prdId: prd.id,
      assignedAgent: 'me',
      metadata: {
        sourceSpecifications: [spec.id],
        acceptanceCriteria: [
          'Search as user types (debounced 300ms)',
          'Show results in dropdown',
          'Highlight matching text',
          'Show "No results" message when empty'
        ]
      }
    });

    const retrieved = taskGet(db, { id: implTask.id });
    assert(retrieved !== null, 'Task should exist');
    assertContains(retrieved.description || '', 'debounced 300ms', 'Description should include acceptance criteria');
    assert(retrieved.metadata.acceptanceCriteria, 'Should have acceptanceCriteria in metadata');
    assertEquals(retrieved.metadata.acceptanceCriteria.length, 4, 'Should have 4 acceptance criteria');
  });
}

// ============================================================================
// TEST SUITE: IMPLEMENTATION AGENT READS SOURCE SPECIFICATION
// ============================================================================

async function testImplementationAgentReadsSpec(db: MockDatabaseClient) {
  console.log('\n' + '='.repeat(70));
  console.log('TEST SUITE: Implementation Agent Reads Specification');
  console.log('='.repeat(70) + '\n');

  await runTest('Implementation agent retrieves specification from task metadata', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'User Auth',
      content: 'User authentication'
    });

    const specTask = await taskCreate(db, {
      title: 'Design auth flow',
      prdId: prd.id,
      assignedAgent: 'uxd'
    });

    const spec = await workProductStore(db, {
      taskId: specTask.id,
      type: 'specification',
      title: 'Auth Flow Specification',
      content: `# Auth Flow Specification

## Login Flow
1. User enters email/password
2. System validates credentials
3. System generates JWT token
4. Client stores token in localStorage

## Security Requirements
- Hash passwords with bcrypt
- JWT expires after 1 hour
- Refresh token valid for 7 days`
    });

    const implTask = await taskCreate(db, {
      title: 'Implement auth endpoints',
      prdId: prd.id,
      assignedAgent: 'me',
      metadata: {
        sourceSpecifications: [spec.id]
      }
    });

    // Implementation agent gets task
    const task = taskGet(db, { id: implTask.id });
    assert(task !== null, 'Task should exist');
    assert(task.metadata.sourceSpecifications, 'Should have specification references');

    // Implementation agent retrieves specification
    const specId = task.metadata.sourceSpecifications[0];
    const specification = workProductGet(db, { id: specId });

    assert(specification !== null, 'Specification should be retrievable');
    assertEquals(specification.type, 'specification', 'Should be specification type');
    assertContains(specification.content, 'Login Flow', 'Should contain login flow');
    assertContains(specification.content, 'Security Requirements', 'Should contain security requirements');
  });

  await runTest('Implementation agent has access to full specification content', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'API Documentation',
      content: 'Generate API docs'
    });

    const specTask = await taskCreate(db, {
      title: 'Design API structure',
      prdId: prd.id,
      assignedAgent: 'ta'
    });

    const specContent = `# API Documentation Specification

## Endpoints
### GET /api/users
Returns list of users

**Response:**
\`\`\`json
{
  "users": [
    { "id": 1, "name": "John" }
  ]
}
\`\`\`

### POST /api/users
Creates a new user

**Request:**
\`\`\`json
{
  "name": "Jane",
  "email": "jane@example.com"
}
\`\`\`

## Authentication
All endpoints require Bearer token in Authorization header.

## Rate Limiting
100 requests per minute per IP.`;

    const spec = await workProductStore(db, {
      taskId: specTask.id,
      type: 'specification',
      title: 'API Structure Specification',
      content: specContent
    });

    const implTask = await taskCreate(db, {
      title: 'Generate API documentation',
      prdId: prd.id,
      assignedAgent: 'doc',
      metadata: {
        sourceSpecifications: [spec.id]
      }
    });

    // Documentation agent retrieves full specification
    const task = taskGet(db, { id: implTask.id });
    const specId = task!.metadata.sourceSpecifications[0];
    const specification = workProductGet(db, { id: specId });

    assert(specification !== null, 'Should retrieve specification');
    assertEquals(specification.content, specContent, 'Should have full content');
    assertGreaterThan(specification.content.length, 400, 'Content should be substantial');
  });
}

// ============================================================================
// TEST SUITE: MULTIPLE SPECIFICATIONS CONSOLIDATED
// ============================================================================

async function testMultipleSpecificationsConsolidated(db: MockDatabaseClient) {
  console.log('\n' + '='.repeat(70));
  console.log('TEST SUITE: Multiple Specifications Consolidated');
  console.log('='.repeat(70) + '\n');

  await runTest('Task references multiple source specifications', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Landing Page',
      content: 'Create landing page'
    });

    // Create specification tasks
    const uxTask = await taskCreate(db, {
      title: 'Design landing page UX',
      prdId: prd.id,
      assignedAgent: 'uxd'
    });

    const uiTask = await taskCreate(db, {
      title: 'Design landing page UI',
      prdId: prd.id,
      assignedAgent: 'uids'
    });

    const copyTask = await taskCreate(db, {
      title: 'Write landing page copy',
      prdId: prd.id,
      assignedAgent: 'cw'
    });

    // Create specifications
    const uxSpec = await workProductStore(db, {
      taskId: uxTask.id,
      type: 'specification',
      title: 'Landing Page UX Specification',
      content: 'UX flow and interaction patterns'
    });

    const uiSpec = await workProductStore(db, {
      taskId: uiTask.id,
      type: 'specification',
      title: 'Landing Page UI Specification',
      content: 'Visual design and components'
    });

    const copySpec = await workProductStore(db, {
      taskId: copyTask.id,
      type: 'specification',
      title: 'Landing Page Copy Specification',
      content: 'Headlines, CTAs, and microcopy'
    });

    // TA creates implementation task referencing all specifications
    const implTask = await taskCreate(db, {
      title: 'Implement landing page',
      prdId: prd.id,
      assignedAgent: 'uid',
      metadata: {
        sourceSpecifications: [uxSpec.id, uiSpec.id, copySpec.id]
      }
    });

    const retrieved = taskGet(db, { id: implTask.id });
    assert(retrieved !== null, 'Task should exist');
    assertEquals(retrieved.metadata.sourceSpecifications.length, 3, 'Should reference 3 specifications');
  });

  await runTest('All specifications are discoverable and accessible', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Mobile App Onboarding',
      content: 'Create onboarding flow'
    });

    // Create multiple specification tasks
    const tasks = [
      await taskCreate(db, { title: 'UX spec', prdId: prd.id, assignedAgent: 'uxd' }),
      await taskCreate(db, { title: 'UI spec', prdId: prd.id, assignedAgent: 'uids' }),
      await taskCreate(db, { title: 'Copy spec', prdId: prd.id, assignedAgent: 'cw' })
    ];

    // Create specifications
    const specs = [];
    for (let i = 0; i < tasks.length; i++) {
      const spec = await workProductStore(db, {
        taskId: tasks[i].id,
        type: 'specification',
        title: `Onboarding Spec ${i + 1}`,
        content: `Specification content ${i + 1}`
      });
      specs.push(spec);
    }

    // Verify all specifications are discoverable
    const allSpecs = workProductList(db, { type: 'specification' });
    assertEquals(allSpecs.length, 3, 'Should discover all 3 specifications');

    // Verify all specifications are accessible
    for (const specSummary of allSpecs) {
      const fullSpec = workProductGet(db, { id: specSummary.id });
      assert(fullSpec !== null, `Specification ${specSummary.id} should be accessible`);
      assertEquals(fullSpec.type, 'specification', 'Should be specification type');
    }
  });
}

// ============================================================================
// TEST SUITE: NO SPECIFICATIONS EXIST (FALLBACK CASE)
// ============================================================================

async function testNoSpecificationsFallback(db: MockDatabaseClient) {
  console.log('\n' + '='.repeat(70));
  console.log('TEST SUITE: No Specifications Fallback');
  console.log('='.repeat(70) + '\n');

  await runTest('Task creation proceeds without errors when no specifications exist', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Quick Bug Fix',
      content: 'Fix reported bug'
    });

    // TA creates task without any specifications
    const task = await taskCreate(db, {
      title: 'Fix login redirect bug',
      description: 'User not redirected after login',
      prdId: prd.id,
      assignedAgent: 'me',
      metadata: {
        sourceSpecifications: []
      }
    });

    const retrieved = taskGet(db, { id: task.id });
    assert(retrieved !== null, 'Task should be created successfully');
    assert(Array.isArray(retrieved.metadata.sourceSpecifications), 'Should have sourceSpecifications array');
    assertEquals(retrieved.metadata.sourceSpecifications.length, 0, 'Should be empty array');
  });

  await runTest('Task notes indicate creation without domain specification', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Emergency Fix',
      content: 'Critical production issue'
    });

    // TA creates task without specifications
    const task = await taskCreate(db, {
      title: 'Fix production crash',
      prdId: prd.id,
      assignedAgent: 'me',
      notes: 'Created without domain specification - critical fix required',
      metadata: {
        sourceSpecifications: []
      }
    });

    const retrieved = taskGet(db, { id: task.id });
    assert(retrieved !== null, 'Task should exist');
    assertContains(retrieved.notes || '', 'without domain specification', 'Notes should indicate no specification');
  });

  await runTest('Implementation can proceed without specification reference', async () => {
    db.reset();

    const prd = await prdCreate(db, {
      title: 'Hotfix',
      content: 'Urgent hotfix'
    });

    const task = await taskCreate(db, {
      title: 'Apply hotfix',
      prdId: prd.id,
      assignedAgent: 'me',
      metadata: {
        sourceSpecifications: []
      }
    });

    // Implementation agent proceeds without specification
    const wp = await workProductStore(db, {
      taskId: task.id,
      type: 'implementation',
      title: 'Hotfix Implementation',
      content: 'Applied fix to production issue'
    });

    assert(wp.id !== '', 'Should create work product successfully');
    const retrieved = workProductGet(db, { id: wp.id });
    assert(retrieved !== null, 'Work product should exist');
    assertEquals(retrieved.type, 'implementation', 'Should be implementation type');
  });
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function runAllTests() {
  console.log('\n' + '='.repeat(70));
  console.log('SPECIFICATION WORKFLOW INTEGRATION TESTS');
  console.log('Testing: Work Product → TA Review → Implementation');
  console.log('='.repeat(70));

  const db = new MockDatabaseClient();

  await testDomainAgentCreatesSpecification(db);
  await testTADiscoversSpecifications(db);
  await testTACreatesSpecInformedTasks(db);
  await testImplementationAgentReadsSpec(db);
  await testMultipleSpecificationsConsolidated(db);
  await testNoSpecificationsFallback(db);

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
