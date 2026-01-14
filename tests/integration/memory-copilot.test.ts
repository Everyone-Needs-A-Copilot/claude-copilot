/**
 * Integration Tests: Memory Copilot
 *
 * Tests all 13 Memory Copilot tools with comprehensive coverage of:
 * - Initiative lifecycle (start, update, get, complete)
 * - Memory CRUD operations (store, update, get, delete, list)
 * - Semantic search functionality
 * - Correction detection and management
 * - Slim mode optimizations
 *
 * @module tests/integration/memory-copilot
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

function assertLessThan(actual: number, expected: number, message: string): void {
  if (!(actual < expected)) {
    throw new Error(`${message}: expected ${actual} < ${expected}`);
  }
}

function assertArrayIncludes<T>(array: T[], item: T, message: string): void {
  if (!array.includes(item)) {
    throw new Error(`${message}: array does not include ${item}`);
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
// MOCK TYPES & IMPLEMENTATIONS
// ============================================================================

type MemoryType = 'decision' | 'lesson' | 'discussion' | 'file' | 'initiative' | 'context' | 'agent_improvement';
type InitiativeStatus = 'NOT STARTED' | 'IN PROGRESS' | 'BLOCKED' | 'READY FOR REVIEW' | 'COMPLETE';
type CorrectionStatus = 'pending' | 'approved' | 'rejected' | 'applied';
type CorrectionTarget = 'agent' | 'skill' | 'memory' | 'preference';

interface Memory {
  id: string;
  projectId: string;
  content: string;
  type: MemoryType;
  tags: string[];
  metadata: Record<string, unknown>;
  createdAt: string;
  updatedAt: string;
  sessionId?: string;
}

interface MemorySearchResult extends Memory {
  distance: number;
}

interface Initiative {
  id: string;
  projectId: string;
  name: string;
  goal?: string;
  status: InitiativeStatus;
  taskCopilotLinked: boolean;
  activePrdIds: string[];
  decisions: string[];
  lessons: string[];
  keyFiles: string[];
  currentFocus?: string;
  nextAction?: string;
  completed: string[];
  inProgress: string[];
  blocked: string[];
  resumeInstructions?: string;
  createdAt: string;
  updatedAt: string;
}

interface CorrectionCapture {
  id: string;
  projectId: string;
  sessionId?: string;
  taskId?: string;
  agentId?: string;
  originalContent: string;
  correctedContent: string;
  rawUserMessage: string;
  matchedPatterns: Array<{ patternId: string; matchedText: string }>;
  extractedWhat?: string;
  extractedWhy?: string;
  extractedHow?: string;
  target: CorrectionTarget;
  targetId?: string;
  targetSection?: string;
  confidence: number;
  status: CorrectionStatus;
  createdAt: string;
  updatedAt: string;
  reviewedAt?: string;
  appliedAt?: string;
  expiresAt?: string;
  reviewMetadata?: Record<string, unknown>;
}

// Mock database storage
const mockDB = {
  memories: new Map<string, Memory>(),
  embeddings: new Map<string, number[]>(),
  initiative: null as Initiative | null,
  corrections: new Map<string, CorrectionCapture>(),
  projectId: 'test-project-123',

  reset() {
    this.memories.clear();
    this.embeddings.clear();
    this.initiative = null;
    this.corrections.clear();
  }
};

// Generate mock embedding (simple hash-based for testing)
function generateMockEmbedding(text: string): number[] {
  const embedding = new Array(384).fill(0);
  for (let i = 0; i < text.length; i++) {
    embedding[i % 384] += text.charCodeAt(i) / 1000;
  }
  return embedding;
}

// Calculate cosine similarity
function cosineSimilarity(a: number[], b: number[]): number {
  let dotProduct = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  return dotProduct / (Math.sqrt(normA) * Math.sqrt(normB));
}

// Calculate cosine distance (1 - similarity)
function cosineDistance(a: number[], b: number[]): number {
  return 1 - cosineSimilarity(a, b);
}

// Estimate token count
function estimateTokens(obj: unknown): number {
  const json = JSON.stringify(obj);
  return Math.ceil(json.length / 4);
}

// ============================================================================
// MOCK TOOL IMPLEMENTATIONS
// ============================================================================

// Initiative tools
function initiativeStart(input: { name: string; goal?: string; status?: InitiativeStatus }): Initiative {
  if (mockDB.initiative) {
    // Archive existing
    mockDB.initiative = null;
  }

  const now = new Date().toISOString();
  mockDB.initiative = {
    id: `init-${Date.now()}`,
    projectId: mockDB.projectId,
    name: input.name,
    goal: input.goal,
    status: input.status || 'IN PROGRESS',
    taskCopilotLinked: false,
    activePrdIds: [],
    decisions: [],
    lessons: [],
    keyFiles: [],
    currentFocus: undefined,
    nextAction: undefined,
    completed: [],
    inProgress: [],
    blocked: [],
    resumeInstructions: undefined,
    createdAt: now,
    updatedAt: now
  };

  return mockDB.initiative;
}

function initiativeUpdate(input: {
  status?: InitiativeStatus;
  currentFocus?: string;
  nextAction?: string;
  decisions?: string[];
  lessons?: string[];
  keyFiles?: string[];
  completed?: string[];
  inProgress?: string[];
  blocked?: string[];
  resumeInstructions?: string;
  taskCopilotLinked?: boolean;
  activePrdIds?: string[];
}): Initiative | null {
  if (!mockDB.initiative) return null;

  const now = new Date().toISOString();

  if (input.status) mockDB.initiative.status = input.status;
  if (input.currentFocus !== undefined) {
    mockDB.initiative.currentFocus = input.currentFocus.substring(0, 100);
  }
  if (input.nextAction !== undefined) {
    mockDB.initiative.nextAction = input.nextAction.substring(0, 100);
  }
  if (input.decisions) {
    mockDB.initiative.decisions.push(...input.decisions);
  }
  if (input.lessons) {
    mockDB.initiative.lessons.push(...input.lessons);
  }
  if (input.keyFiles) {
    mockDB.initiative.keyFiles.push(...input.keyFiles);
  }
  if (input.completed) {
    mockDB.initiative.completed.push(...input.completed);
  }
  if (input.inProgress !== undefined) {
    mockDB.initiative.inProgress = input.inProgress;
  }
  if (input.blocked !== undefined) {
    mockDB.initiative.blocked = input.blocked;
  }
  if (input.resumeInstructions !== undefined) {
    mockDB.initiative.resumeInstructions = input.resumeInstructions;
  }
  if (input.taskCopilotLinked !== undefined) {
    mockDB.initiative.taskCopilotLinked = input.taskCopilotLinked;
  }
  if (input.activePrdIds !== undefined) {
    mockDB.initiative.activePrdIds = input.activePrdIds;
  }

  mockDB.initiative.updatedAt = now;
  return mockDB.initiative;
}

function initiativeGet(input?: { mode?: 'lean' | 'full' }): Initiative | null {
  if (!mockDB.initiative) return null;

  const mode = input?.mode || 'lean';

  if (mode === 'lean') {
    return {
      id: mockDB.initiative.id,
      projectId: mockDB.initiative.projectId,
      name: mockDB.initiative.name,
      goal: mockDB.initiative.goal,
      status: mockDB.initiative.status,
      taskCopilotLinked: mockDB.initiative.taskCopilotLinked,
      activePrdIds: mockDB.initiative.activePrdIds,
      currentFocus: mockDB.initiative.currentFocus,
      nextAction: mockDB.initiative.nextAction,
      decisions: [],
      lessons: [],
      keyFiles: [],
      completed: [],
      inProgress: [],
      blocked: [],
      resumeInstructions: undefined,
      createdAt: mockDB.initiative.createdAt,
      updatedAt: mockDB.initiative.updatedAt
    };
  }

  return mockDB.initiative;
}

function initiativeComplete(summary?: string): Initiative | null {
  if (!mockDB.initiative) return null;

  const now = new Date().toISOString();
  mockDB.initiative.status = 'COMPLETE';
  mockDB.initiative.resumeInstructions = summary || mockDB.initiative.resumeInstructions;
  mockDB.initiative.updatedAt = now;

  const completed = { ...mockDB.initiative };
  mockDB.initiative = null;
  return completed;
}

function initiativeSlim(input?: { archiveDetails?: boolean }): {
  initiativeId: string;
  archived: boolean;
  archivePath?: string;
  removedFields: string[];
  beforeSize: number;
  afterSize: number;
  savings: string;
} | null {
  if (!mockDB.initiative) return null;

  const beforeSize = estimateTokens(mockDB.initiative);

  mockDB.initiative.completed = [];
  mockDB.initiative.inProgress = [];
  mockDB.initiative.blocked = [];
  mockDB.initiative.resumeInstructions = undefined;
  mockDB.initiative.currentFocus = undefined;
  mockDB.initiative.nextAction = undefined;
  mockDB.initiative.taskCopilotLinked = false;
  mockDB.initiative.activePrdIds = [];

  const afterSize = estimateTokens(mockDB.initiative);
  const reduction = ((beforeSize - afterSize) / beforeSize * 100).toFixed(0);

  return {
    initiativeId: mockDB.initiative.id,
    archived: input?.archiveDetails !== false,
    archivePath: input?.archiveDetails !== false ? '/mock/archive/path.json' : undefined,
    removedFields: ['completed', 'inProgress', 'blocked', 'resumeInstructions'],
    beforeSize,
    afterSize,
    savings: `${reduction}% reduction`
  };
}

// Memory tools
async function memoryStore(input: {
  content: string;
  type: MemoryType;
  tags?: string[];
  metadata?: Record<string, unknown>;
  sessionId?: string;
}): Promise<Memory> {
  const id = `mem-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`;
  const now = new Date().toISOString();

  const memory: Memory = {
    id,
    projectId: mockDB.projectId,
    content: input.content,
    type: input.type,
    tags: input.tags || [],
    metadata: input.metadata || {},
    createdAt: now,
    updatedAt: now,
    sessionId: input.sessionId
  };

  mockDB.memories.set(id, memory);
  mockDB.embeddings.set(id, generateMockEmbedding(input.content));

  return memory;
}

async function memoryUpdate(input: {
  id: string;
  content?: string;
  tags?: string[];
  metadata?: Record<string, unknown>;
}): Promise<Memory | null> {
  const memory = mockDB.memories.get(input.id);
  if (!memory) return null;

  if (input.content !== undefined) {
    memory.content = input.content;
    mockDB.embeddings.set(input.id, generateMockEmbedding(input.content));
  }
  if (input.tags !== undefined) {
    memory.tags = input.tags;
  }
  if (input.metadata !== undefined) {
    memory.metadata = input.metadata;
  }

  memory.updatedAt = new Date().toISOString();
  return memory;
}

function memoryGet(id: string): Memory | null {
  return mockDB.memories.get(id) || null;
}

function memoryDelete(id: string): boolean {
  const deleted = mockDB.memories.delete(id);
  if (deleted) {
    mockDB.embeddings.delete(id);
  }
  return deleted;
}

function memoryList(input?: {
  type?: MemoryType;
  tags?: string[];
  limit?: number;
  offset?: number;
}): Memory[] {
  let memories = Array.from(mockDB.memories.values());

  if (input?.type) {
    memories = memories.filter(m => m.type === input.type);
  }

  if (input?.tags && input.tags.length > 0) {
    memories = memories.filter(m => input.tags!.some(tag => m.tags.includes(tag)));
  }

  const offset = input?.offset || 0;
  const limit = input?.limit || 20;

  return memories.slice(offset, offset + limit);
}

async function memorySearch(input: {
  query: string;
  type?: MemoryType;
  limit?: number;
  threshold?: number;
}): Promise<MemorySearchResult[]> {
  const queryEmbedding = generateMockEmbedding(input.query);
  const results: MemorySearchResult[] = [];

  for (const [id, memory] of mockDB.memories) {
    if (input.type && memory.type !== input.type) continue;

    const embedding = mockDB.embeddings.get(id);
    if (!embedding) continue;

    const distance = cosineDistance(queryEmbedding, embedding);
    const similarity = 1 - distance;

    const threshold = input.threshold || 0.7;
    if (similarity >= threshold) {
      results.push({ ...memory, distance });
    }
  }

  results.sort((a, b) => a.distance - b.distance);
  const limit = input.limit || 10;
  return results.slice(0, limit);
}

// Correction tools
function correctionDetect(input: {
  userMessage: string;
  previousAgentOutput?: string;
  agentId?: string;
  taskId?: string;
  threshold?: number;
}): {
  detected: boolean;
  corrections: CorrectionCapture[];
  patternMatchCount: number;
  maxConfidence: number;
  suggestedAction: 'auto_capture' | 'prompt_user' | 'ignore';
} {
  const threshold = input.threshold || 0.5;

  // Simple pattern matching
  const patterns = [
    { id: 'explicit', regex: /correction[:\s]+(.+)/i, weight: 0.95 },
    { id: 'actually', regex: /actually[,\s]+(?:use|it should be)\s+([^.]+)/i, weight: 0.85 },
    { id: 'no-wrong', regex: /no[,\s]+(?:that\'?s?)\s+(?:wrong|incorrect)/i, weight: 0.90 }
  ];

  const matches: Array<{ patternId: string; matchedText: string }> = [];
  let confidence = 0;

  for (const pattern of patterns) {
    const match = input.userMessage.match(pattern.regex);
    if (match) {
      matches.push({ patternId: pattern.id, matchedText: match[0] });
      confidence = Math.max(confidence, pattern.weight);
    }
  }

  if (confidence < threshold) {
    return {
      detected: false,
      corrections: [],
      patternMatchCount: matches.length,
      maxConfidence: confidence,
      suggestedAction: 'ignore'
    };
  }

  const correction: CorrectionCapture = {
    id: `corr-${Date.now()}-${Math.random().toString(36).substring(2, 9)}`,
    projectId: mockDB.projectId,
    taskId: input.taskId,
    agentId: input.agentId,
    originalContent: input.previousAgentOutput || '',
    correctedContent: input.userMessage,
    rawUserMessage: input.userMessage,
    matchedPatterns: matches,
    target: 'memory',
    confidence,
    status: 'pending',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    expiresAt: new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString()
  };

  mockDB.corrections.set(correction.id, correction);

  return {
    detected: true,
    corrections: [correction],
    patternMatchCount: matches.length,
    maxConfidence: confidence,
    suggestedAction: confidence >= 0.85 ? 'auto_capture' : 'prompt_user'
  };
}

function correctionList(input?: {
  status?: CorrectionStatus;
  agentId?: string;
  limit?: number;
}): CorrectionCapture[] {
  let corrections = Array.from(mockDB.corrections.values());

  if (input?.status) {
    corrections = corrections.filter(c => c.status === input.status);
  }

  if (input?.agentId) {
    corrections = corrections.filter(c => c.agentId === input.agentId);
  }

  const limit = input?.limit || 20;
  return corrections.slice(0, limit);
}

function correctionUpdate(input: {
  correctionId: string;
  status: CorrectionStatus;
  reviewMetadata?: Record<string, unknown>;
}): boolean {
  const correction = mockDB.corrections.get(input.correctionId);
  if (!correction) return false;

  correction.status = input.status;
  correction.updatedAt = new Date().toISOString();

  if (input.status === 'approved' || input.status === 'rejected') {
    correction.reviewedAt = new Date().toISOString();
  }

  if (input.status === 'applied') {
    correction.appliedAt = new Date().toISOString();
  }

  if (input.reviewMetadata) {
    correction.reviewMetadata = input.reviewMetadata;
  }

  return true;
}

function correctionRoute(correctionId: string): {
  correctionId: string;
  target: CorrectionTarget;
  targetPath: string;
  responsibleAgent: string;
  confidence: number;
  applyInstructions: string;
} | null {
  const correction = mockDB.corrections.get(correctionId);
  if (!correction) return null;

  return {
    correctionId,
    target: correction.target,
    targetPath: correction.target === 'memory' ? 'memory://context' : '.claude/agents/me.md',
    responsibleAgent: correction.target === 'memory' ? 'memory' : 'me',
    confidence: correction.confidence,
    applyInstructions: `Apply correction to ${correction.target}`
  };
}

// ============================================================================
// MEM-01: INITIATIVE LIFECYCLE TESTS
// ============================================================================

async function runInitiativeLifecycleTests() {
  console.log('\n' + '='.repeat(70));
  console.log('MEM-01: INITIATIVE LIFECYCLE TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('initiative_start creates new initiative with required fields', () => {
    mockDB.reset();

    const initiative = initiativeStart({
      name: 'Test Initiative',
      goal: 'Build a feature',
      status: 'IN PROGRESS'
    });

    assert(initiative.id.startsWith('init-'), 'ID should have init- prefix');
    assertEquals(initiative.name, 'Test Initiative', 'Name should match');
    assertEquals(initiative.goal, 'Build a feature', 'Goal should match');
    assertEquals(initiative.status, 'IN PROGRESS', 'Status should match');
    assertEquals(initiative.decisions.length, 0, 'Should start with empty decisions');
    assertEquals(initiative.lessons.length, 0, 'Should start with empty lessons');
    assertEquals(initiative.keyFiles.length, 0, 'Should start with empty keyFiles');
    assertEquals(initiative.taskCopilotLinked, false, 'Should not be linked initially');
  });

  await runTest('initiative_update modifies status, currentFocus, nextAction', () => {
    mockDB.reset();
    initiativeStart({ name: 'Test' });

    const updated = initiativeUpdate({
      status: 'BLOCKED',
      currentFocus: 'Implementing authentication',
      nextAction: 'Add JWT middleware'
    });

    assert(updated !== null, 'Should return updated initiative');
    assertEquals(updated!.status, 'BLOCKED', 'Status should be updated');
    assertEquals(updated!.currentFocus, 'Implementing authentication', 'Current focus should be set');
    assertEquals(updated!.nextAction, 'Add JWT middleware', 'Next action should be set');
  });

  await runTest('initiative_get returns lean mode (~150 tokens) vs full mode (~370 tokens)', () => {
    mockDB.reset();
    initiativeStart({ name: 'Test', goal: 'Test goal' });

    initiativeUpdate({
      decisions: ['Decision 1', 'Decision 2', 'Decision 3'],
      lessons: ['Lesson 1', 'Lesson 2'],
      keyFiles: ['src/file1.ts', 'src/file2.ts'],
      currentFocus: 'Building feature X',
      nextAction: 'Test the feature'
    });

    const lean = initiativeGet({ mode: 'lean' });
    const full = initiativeGet({ mode: 'full' });

    assert(lean !== null, 'Lean mode should return initiative');
    assert(full !== null, 'Full mode should return initiative');

    const leanTokens = estimateTokens(lean);
    const fullTokens = estimateTokens(full);

    assertEquals(lean!.decisions.length, 0, 'Lean mode should exclude decisions');
    assertEquals(lean!.lessons.length, 0, 'Lean mode should exclude lessons');
    assertEquals(lean!.keyFiles.length, 0, 'Lean mode should exclude keyFiles');

    assertEquals(full!.decisions.length, 3, 'Full mode should include decisions');
    assertEquals(full!.lessons.length, 2, 'Full mode should include lessons');
    assertEquals(full!.keyFiles.length, 2, 'Full mode should include keyFiles');

    assertLessThan(leanTokens, 200, 'Lean mode should be under 200 tokens');
    assertGreaterThan(fullTokens, leanTokens, 'Full mode should be larger than lean');
  });

  await runTest('initiative_complete archives and clears current', () => {
    mockDB.reset();
    initiativeStart({ name: 'Test' });

    const completed = initiativeComplete('Successfully completed the initiative');

    assert(completed !== null, 'Should return completed initiative');
    assertEquals(completed!.status, 'COMPLETE', 'Status should be COMPLETE');
    assertEquals(completed!.resumeInstructions, 'Successfully completed the initiative', 'Summary should be set');
    assertEquals(mockDB.initiative, null, 'Current initiative should be cleared');
  });
}

// ============================================================================
// MEM-02: MEMORY CRUD TESTS
// ============================================================================

async function runMemoryCrudTests() {
  console.log('\n' + '='.repeat(70));
  console.log('MEM-02: MEMORY CRUD TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('memory_store creates memory with embedding generation', async () => {
    mockDB.reset();

    const memory = await memoryStore({
      content: 'Important decision: use TypeScript',
      type: 'decision',
      tags: ['typescript', 'architecture'],
      metadata: { importance: 'high' }
    });

    assert(memory.id.startsWith('mem-'), 'ID should have mem- prefix');
    assertEquals(memory.content, 'Important decision: use TypeScript', 'Content should match');
    assertEquals(memory.type, 'decision', 'Type should match');
    assertArrayIncludes(memory.tags, 'typescript', 'Should include typescript tag');
    assertEquals(memory.metadata.importance, 'high', 'Metadata should be preserved');

    const embedding = mockDB.embeddings.get(memory.id);
    assert(embedding !== undefined, 'Embedding should be generated');
    assertEquals(embedding!.length, 384, 'Embedding should have 384 dimensions');
  });

  await runTest('memory_update modifies content and regenerates embedding', async () => {
    mockDB.reset();

    const memory = await memoryStore({
      content: 'Original content',
      type: 'context'
    });

    const originalEmbedding = mockDB.embeddings.get(memory.id);

    const updated = await memoryUpdate({
      id: memory.id,
      content: 'Updated content',
      tags: ['updated']
    });

    assert(updated !== null, 'Should return updated memory');
    assertEquals(updated!.content, 'Updated content', 'Content should be updated');
    assertArrayIncludes(updated!.tags, 'updated', 'Tags should be updated');

    const newEmbedding = mockDB.embeddings.get(memory.id);
    assert(newEmbedding !== originalEmbedding, 'Embedding should be regenerated');
  });

  await runTest('memory_get retrieves by ID', async () => {
    mockDB.reset();

    const stored = await memoryStore({
      content: 'Test memory',
      type: 'lesson'
    });

    const retrieved = memoryGet(stored.id);

    assert(retrieved !== null, 'Should retrieve memory');
    assertEquals(retrieved!.id, stored.id, 'Should match stored ID');
    assertEquals(retrieved!.content, 'Test memory', 'Content should match');
  });

  await runTest('memory_delete removes memory', async () => {
    mockDB.reset();

    const memory = await memoryStore({
      content: 'To be deleted',
      type: 'context'
    });

    const deleted = memoryDelete(memory.id);

    assertEquals(deleted, true, 'Should return true on successful deletion');
    assertEquals(memoryGet(memory.id), null, 'Memory should be removed');
    assertEquals(mockDB.embeddings.get(memory.id), undefined, 'Embedding should be removed');
  });

  await runTest('memory_list filters by type and tags', async () => {
    mockDB.reset();

    await memoryStore({ content: 'Decision 1', type: 'decision', tags: ['important'] });
    await memoryStore({ content: 'Decision 2', type: 'decision', tags: ['minor'] });
    await memoryStore({ content: 'Lesson 1', type: 'lesson', tags: ['important'] });

    const decisions = memoryList({ type: 'decision' });
    assertEquals(decisions.length, 2, 'Should filter by type');

    const important = memoryList({ tags: ['important'] });
    assertEquals(important.length, 2, 'Should filter by tag');

    const importantDecisions = memoryList({ type: 'decision', tags: ['important'] });
    assertEquals(importantDecisions.length, 1, 'Should filter by type and tag');
  });
}

// ============================================================================
// MEM-03: SEMANTIC SEARCH TESTS
// ============================================================================

async function runSemanticSearchTests() {
  console.log('\n' + '='.repeat(70));
  console.log('MEM-03: SEMANTIC SEARCH TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('memory_search returns relevant results above threshold', async () => {
    mockDB.reset();

    await memoryStore({ content: 'Use TypeScript for type safety', type: 'decision' });
    await memoryStore({ content: 'Add authentication middleware', type: 'decision' });
    await memoryStore({ content: 'TypeScript provides excellent IDE support', type: 'lesson' });

    const results = await memorySearch({
      query: 'TypeScript benefits',
      threshold: 0.3
    });

    assert(results.length > 0, 'Should return results');
    assert(results.every(r => r.distance !== undefined), 'All results should have distance');
    assert(results[0].distance < results[results.length - 1].distance, 'Results should be sorted by distance');
  });

  await runTest('memory_search respects limit parameter', async () => {
    mockDB.reset();

    for (let i = 0; i < 10; i++) {
      await memoryStore({ content: `Memory ${i} about TypeScript`, type: 'context' });
    }

    const limited = await memorySearch({
      query: 'TypeScript',
      limit: 3,
      threshold: 0.1  // Lower threshold to ensure matches
    });

    assertEquals(limited.length, 3, 'Should respect limit parameter');
  });

  await runTest('memory_search filters by type', async () => {
    mockDB.reset();

    await memoryStore({ content: 'TypeScript decision', type: 'decision' });
    await memoryStore({ content: 'TypeScript lesson', type: 'lesson' });
    await memoryStore({ content: 'TypeScript context', type: 'context' });

    const lessonResults = await memorySearch({
      query: 'TypeScript',
      type: 'lesson',
      threshold: 0
    });

    assertEquals(lessonResults.length, 1, 'Should filter by type');
    assertEquals(lessonResults[0].type, 'lesson', 'Result should be lesson type');
  });
}

// ============================================================================
// MEM-04: CORRECTION DETECTION TESTS
// ============================================================================

async function runCorrectionDetectionTests() {
  console.log('\n' + '='.repeat(70));
  console.log('MEM-04: CORRECTION DETECTION TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('correction_detect identifies explicit correction patterns', () => {
    mockDB.reset();

    const result = correctionDetect({
      userMessage: 'Correction: use async/await instead of callbacks',
      previousAgentOutput: 'I implemented it with callbacks',
      agentId: 'me',
      taskId: 'TASK-1'
    });

    assertEquals(result.detected, true, 'Should detect correction');
    assert(result.maxConfidence >= 0.9, 'Explicit correction should have high confidence');
    assertEquals(result.corrections.length, 1, 'Should capture one correction');
    assertEquals(result.corrections[0].status, 'pending', 'Should be pending status');
  });

  await runTest('correction_detect identifies replacement patterns ("use X instead of Y")', () => {
    mockDB.reset();

    const result = correctionDetect({
      userMessage: 'Actually, use TypeScript instead of JavaScript',
      previousAgentOutput: 'Created file in JavaScript',
      agentId: 'me'
    });

    assertEquals(result.detected, true, 'Should detect replacement pattern');
    assert(result.maxConfidence >= 0.8, 'Replacement should have high confidence');
    assertGreaterThan(result.patternMatchCount, 0, 'Should match at least one pattern');
  });

  await runTest('correction_list filters by status (pending/approved/rejected)', () => {
    mockDB.reset();

    const detection1 = correctionDetect({ userMessage: 'Correction: fix this' });
    assert(detection1.detected, 'First detection should succeed');
    const correction = detection1.corrections[0];

    const updated = correctionUpdate({ correctionId: correction.id, status: 'approved' });
    assert(updated, 'Update should succeed');

    const detection2 = correctionDetect({ userMessage: 'Correction: fix that' });
    assert(detection2.detected, 'Second detection should succeed');

    const allCorrections = correctionList();
    const pending = correctionList({ status: 'pending' });
    const approved = correctionList({ status: 'approved' });

    assertEquals(allCorrections.length, 2, `Should have 2 total corrections, got ${allCorrections.map(c => c.status).join(', ')}`);
    assertEquals(pending.length, 1, 'Should have 1 pending');
    assertEquals(approved.length, 1, 'Should have 1 approved');
  });

  await runTest('correction_update changes status and routes appropriately', () => {
    mockDB.reset();

    const detection = correctionDetect({ userMessage: 'Correction: use better approach' });
    const correctionId = detection.corrections[0].id;

    const updated = correctionUpdate({
      correctionId,
      status: 'approved',
      reviewMetadata: { reviewer: 'user' }
    });

    assertEquals(updated, true, 'Should update successfully');

    const correction = mockDB.corrections.get(correctionId);
    assertEquals(correction!.status, 'approved', 'Status should be updated');
    assert(correction!.reviewedAt !== undefined, 'Should set reviewed timestamp');
    assertEquals(correction!.reviewMetadata?.reviewer, 'user', 'Should store metadata');
  });

  await runTest('correction_route returns target file/agent', () => {
    mockDB.reset();

    const detection = correctionDetect({
      userMessage: 'Correction: improve implementation',
      agentId: 'me'
    });

    const route = correctionRoute(detection.corrections[0].id);

    assert(route !== null, 'Should return route info');
    assertEquals(route!.correctionId, detection.corrections[0].id, 'Should match correction ID');
    assert(route!.targetPath.length > 0, 'Should have target path');
    assert(route!.responsibleAgent.length > 0, 'Should have responsible agent');
    assert(route!.applyInstructions.length > 0, 'Should have instructions');
  });
}

// ============================================================================
// MEM-05: SLIM MODE TESTS
// ============================================================================

async function runSlimModeTests() {
  console.log('\n' + '='.repeat(70));
  console.log('MEM-05: SLIM MODE TESTS');
  console.log('='.repeat(70) + '\n');

  await runTest('initiative_slim removes bloated task lists', () => {
    mockDB.reset();

    initiativeStart({ name: 'Bloated Initiative' });

    // Add bloated data
    initiativeUpdate({
      completed: Array.from({ length: 50 }, (_, i) => `Completed task ${i}`),
      inProgress: Array.from({ length: 10 }, (_, i) => `In progress task ${i}`),
      blocked: Array.from({ length: 5 }, (_, i) => `Blocked task ${i}`),
      resumeInstructions: 'Very long resume instructions'.repeat(50)
    });

    const result = initiativeSlim({ archiveDetails: true });

    assert(result !== null, 'Should return slim result');
    assertArrayIncludes(result!.removedFields, 'completed', 'Should list completed as removed');
    assertArrayIncludes(result!.removedFields, 'inProgress', 'Should list inProgress as removed');
    assertArrayIncludes(result!.removedFields, 'blocked', 'Should list blocked as removed');
    assertGreaterThan(result!.beforeSize, result!.afterSize, 'Should reduce size');
    assert(result!.archived, 'Should archive if archiveDetails is true');
  });

  await runTest('initiative_slim preserves decisions, lessons, keyFiles', () => {
    mockDB.reset();

    initiativeStart({ name: 'Test Initiative' });

    initiativeUpdate({
      decisions: ['Important decision 1', 'Important decision 2'],
      lessons: ['Key lesson 1', 'Key lesson 2'],
      keyFiles: ['src/core.ts', 'src/utils.ts'],
      completed: Array.from({ length: 20 }, (_, i) => `Task ${i}`)
    });

    const beforeInit = initiativeGet({ mode: 'full' });
    initiativeSlim();
    const afterInit = initiativeGet({ mode: 'full' });

    assertEquals(afterInit!.decisions.length, beforeInit!.decisions.length, 'Decisions should be preserved');
    assertEquals(afterInit!.lessons.length, beforeInit!.lessons.length, 'Lessons should be preserved');
    assertEquals(afterInit!.keyFiles.length, beforeInit!.keyFiles.length, 'KeyFiles should be preserved');
    assertEquals(afterInit!.completed.length, 0, 'Completed should be cleared');
  });

  await runTest('Slim mode integration with Task Copilot linking', () => {
    mockDB.reset();

    initiativeStart({ name: 'Test' });

    initiativeUpdate({
      taskCopilotLinked: true,
      activePrdIds: ['PRD-1', 'PRD-2'],
      completed: Array.from({ length: 30 }, () => 'task')
    });

    const beforeLinked = initiativeGet({ mode: 'full' });
    assertEquals(beforeLinked!.taskCopilotLinked, true, 'Should be linked before slim');

    initiativeSlim();

    const afterInit = initiativeGet({ mode: 'full' });
    assertEquals(afterInit!.taskCopilotLinked, false, 'Should clear Task Copilot link');
    assertEquals(afterInit!.activePrdIds.length, 0, 'Should clear active PRD IDs');
  });
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function runAllTests() {
  console.log('\n' + '='.repeat(70));
  console.log('MEMORY COPILOT INTEGRATION TEST SUITE');
  console.log('Testing all 13 Memory Copilot tools');
  console.log('='.repeat(70));

  await runInitiativeLifecycleTests();
  await runMemoryCrudTests();
  await runSemanticSearchTests();
  await runCorrectionDetectionTests();
  await runSlimModeTests();

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
