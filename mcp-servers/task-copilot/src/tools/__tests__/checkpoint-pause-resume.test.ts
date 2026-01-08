/**
 * Tests for enhanced pause/resume checkpoint functionality
 *
 * Tests the pause/resume flow including:
 * - /pause command creates checkpoint with extended expiry
 * - /continue detects and prioritizes pause checkpoints
 * - Checkpoint metadata includes reason and context
 *
 * Run with: npm run test:pause-resume
 */

import { DatabaseClient } from '../../database.js';
import { initiativeLink } from '../initiative.js';
import { prdCreate } from '../prd.js';
import { taskCreate, taskUpdate, taskList } from '../task.js';
import { checkpointCreate, checkpointGet, checkpointList, checkpointResume } from '../checkpoint.js';
import type { CheckpointCreateInput } from '../../types.js';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

// ============================================================================
// TEST HELPERS
// ============================================================================

let testCount = 0;
let passCount = 0;
let failCount = 0;

function createTestDb(): DatabaseClient {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'pause-resume-test-'));
  return new DatabaseClient('/test/project', tempDir, `test-${Date.now()}`);
}

function log(msg: string): void {
  console.log('  ' + msg);
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error('Assertion failed: ' + message);
  }
}

async function runTest(name: string, fn: () => Promise<void>): Promise<void> {
  testCount++;
  console.log(`\n${testCount}. ${name}`);
  console.log('='.repeat(60));

  try {
    await fn();
    passCount++;
    console.log(`✅ PASS: ${name}\n`);
  } catch (error) {
    failCount++;
    const errorMessage = error instanceof Error ? error.message : String(error);
    console.error(`❌ FAIL: ${name}`);
    console.error(`   Error: ${errorMessage}\n`);
    throw error; // Re-throw to stop execution
  }
}

// ============================================================================
// TEST SUITE 1: /pause command creates checkpoint with extended expiry
// ============================================================================

async function testPauseCheckpointExtendedExpiry(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, {
      initiativeId: 'INIT-001',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content'
    });

    const task = await taskCreate(db, {
      title: 'Feature implementation',
      prdId: prd.id
    });

    await taskUpdate(db, { id: task.id, status: 'in_progress' });
    log('✓ Created in-progress task');

    const input: CheckpointCreateInput = {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      executionStep: 0,
      agentContext: {
        pauseReason: 'Switching to urgent bug',
        pausedBy: 'user',
        pausedAt: new Date().toISOString()
      },
      expiresIn: 10080 // 7 days for manual checkpoints
    };

    const checkpoint = checkpointCreate(db, input);

    assert(checkpoint.id !== undefined, 'Checkpoint should have ID');
    assert(checkpoint.trigger === 'manual', 'Trigger should be manual');
    assert(checkpoint.expiresAt !== null, 'Should have expiry date');
    log(`✓ Created checkpoint: ${checkpoint.id}`);

    // Verify expiry is extended (7 days = 10080 minutes)
    const expiryDate = new Date(checkpoint.expiresAt!);
    const createdDate = new Date();
    const diffMinutes = (expiryDate.getTime() - createdDate.getTime()) / (1000 * 60);

    assert(diffMinutes > 10000, 'Expiry should be ~7 days (>10000 min)');
    assert(diffMinutes < 10100, 'Expiry should be ~7 days (<10100 min)');
    log(`✓ Expiry verified: ${Math.round(diffMinutes)} minutes (~7 days)`);
  } finally {
    db.close();
  }
}

async function testPauseCheckpointMetadata(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-002', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Task', prdId: prd.id });
    await taskUpdate(db, { id: task.id, status: 'in_progress' });

    const pauseReason = 'Context switch to production issue';

    const checkpoint = checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: {
        pauseReason: pauseReason,
        pausedBy: 'user'
      }
    });

    const retrieved = checkpointGet(db, { id: checkpoint.id });

    assert(retrieved !== null, 'Should retrieve checkpoint');
    assert(retrieved!.agentContext !== null, 'Should have agent context');
    assert(retrieved!.agentContext!.pauseReason === pauseReason, 'Pause reason should match');
    assert(retrieved!.agentContext!.pausedBy === 'user', 'PausedBy should be user');

    log(`✓ Pause reason: ${retrieved!.agentContext!.pauseReason}`);
    log(`✓ Paused by: ${retrieved!.agentContext!.pausedBy}`);
  } finally {
    db.close();
  }
}

async function testPauseCheckpointFullContext(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-003', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Database migration', prdId: prd.id });
    await taskUpdate(db, { id: task.id, status: 'in_progress' });

    const input: CheckpointCreateInput = {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      pauseMetadata: {
        pauseReason: 'End of day',
        pausedBy: 'user',
        nextSteps: ['Complete schema migration', 'Update documentation'],
        blockers: ['Waiting for DBA approval'],
        keyFiles: ['migrations/001_users.sql', 'docs/migration-plan.md']
      }
    };

    const checkpoint = checkpointCreate(db, input);
    const retrieved = checkpointGet(db, { id: checkpoint.id });

    assert(retrieved!.agentContext!.pauseReason === 'End of day', 'Pause reason should match');
    assert(retrieved!.agentContext!.pausedBy === 'user', 'PausedBy should match');
    assert(Array.isArray(retrieved!.agentContext!.nextSteps), 'NextSteps should be array');
    assert(retrieved!.agentContext!.nextSteps!.length === 2, 'Should have 2 next steps');
    assert(Array.isArray(retrieved!.agentContext!.blockers), 'Blockers should be array');
    assert(retrieved!.agentContext!.blockers!.length === 1, 'Should have 1 blocker');
    assert(Array.isArray(retrieved!.agentContext!.keyFiles), 'KeyFiles should be array');
    assert(retrieved!.agentContext!.keyFiles!.length === 2, 'Should have 2 key files');
    assert(retrieved!.agentContext!.pausedAt !== undefined, 'Should have timestamp');

    log('✓ All pause metadata fields preserved');
    log(`✓ Next steps: ${retrieved!.agentContext!.nextSteps!.length}`);
    log(`✓ Blockers: ${retrieved!.agentContext!.blockers!.length}`);
    log(`✓ Key files: ${retrieved!.agentContext!.keyFiles!.length}`);
  } finally {
    db.close();
  }
}

async function testPauseMultipleTasks(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-004', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });

    const task1 = await taskCreate(db, { title: 'Task 1', prdId: prd.id });
    const task2 = await taskCreate(db, { title: 'Task 2', prdId: prd.id });
    const task3 = await taskCreate(db, { title: 'Task 3', prdId: prd.id });

    await taskUpdate(db, { id: task1.id, status: 'in_progress' });
    await taskUpdate(db, { id: task2.id, status: 'in_progress' });
    // task3 remains pending

    const pauseReason = 'Lunch break';
    const tasks = taskList(db, { status: 'in_progress' });

    assert(tasks.length === 2, 'Should have 2 in-progress tasks');
    log(`✓ Found ${tasks.length} in-progress tasks`);

    const checkpoints = tasks.map(task => {
      return checkpointCreate(db, {
        taskId: task.id,
        trigger: 'manual',
        executionPhase: 'paused',
        agentContext: {
          pauseReason: pauseReason,
          pausedBy: 'user'
        },
        expiresIn: 10080
      });
    });

    assert(checkpoints.length === 2, 'Should create 2 checkpoints');
    assert(checkpoints.every(cp => cp.trigger === 'manual'), 'All should be manual');
    log(`✓ Created ${checkpoints.length} pause checkpoints`);
  } finally {
    db.close();
  }
}

async function testPauseDraftContent(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-005', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Code review', prdId: prd.id });
    await taskUpdate(db, { id: task.id, status: 'in_progress' });

    const draftContent = `# Code Review Draft

## Files Reviewed
- src/auth/login.ts (partial)

## Issues Found
1. Missing input validation`;

    const checkpoint = checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: {
        pauseReason: 'Meeting started',
        pausedBy: 'user'
      },
      draftContent: draftContent,
      draftType: 'other'
    });

    const retrieved = checkpointGet(db, { id: checkpoint.id });

    assert(retrieved!.draftContent === draftContent, 'Draft content should match');
    assert(retrieved!.draftType === 'other', 'Draft type should match');
    log('✓ Draft content preserved');
    log(`✓ Draft type: ${retrieved!.draftType}`);
  } finally {
    db.close();
  }
}

// ============================================================================
// TEST SUITE 2: /continue detects and prioritizes pause checkpoints
// ============================================================================

async function testContinueDetectsPauseCheckpoint(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-006', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Feature', prdId: prd.id });
    await taskUpdate(db, { id: task.id, status: 'in_progress' });

    // Create pause checkpoint
    const cp1 = checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      executionStep: 0,
      agentContext: {
        pauseReason: 'Interrupted by meeting',
        pausedBy: 'user'
      }
    });
    log(`✓ Created checkpoint 1: ${cp1.id}, sequence: ${cp1.sequence}`);

    // Create auto checkpoint (should not be detected as pause)
    const cp2 = checkpointCreate(db, {
      taskId: task.id,
      trigger: 'auto_status',
      executionPhase: 'implementation',
      executionStep: 1
    });
    log(`✓ Created checkpoint 2: ${cp2.id}, sequence: ${cp2.sequence}`);

    const checkpoints = checkpointList(db, { taskId: task.id });
    log(`✓ Listed checkpoints: ${checkpoints.checkpoints.length}`);
    checkpoints.checkpoints.forEach(cp => {
      log(`  - ${cp.id}: seq=${cp.sequence}, trigger=${cp.trigger}, phase=${cp.phase}`);
    });

    // Note: taskUpdate to in_progress may auto-create a checkpoint, so we check >= 2
    assert(checkpoints.checkpoints.length >= 2, `Should have at least 2 checkpoints but got ${checkpoints.checkpoints.length}`);
    log(`✓ Total checkpoints: ${checkpoints.checkpoints.length}`);

    // Find pause checkpoint
    const pauseCp = checkpoints.checkpoints.find(
      cp => cp.trigger === 'manual' && cp.phase === 'paused'
    );

    assert(pauseCp !== undefined, 'Should find pause checkpoint');
    assert(pauseCp!.trigger === 'manual', 'Should be manual trigger');
    assert(pauseCp!.phase === 'paused', 'Should be paused phase');
    log('✓ Pause checkpoint identified by trigger=manual, phase=paused');

    const fullPauseCp = checkpointGet(db, { id: pauseCp!.id });
    assert(fullPauseCp!.agentContext!.pausedBy === 'user', 'Should have pausedBy');
    assert(fullPauseCp!.agentContext!.pauseReason !== undefined, 'Should have pauseReason');
    log('✓ Pause checkpoint has required metadata');
  } finally {
    db.close();
  }
}

async function testContinuePrioritizesMostRecentPause(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-007', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Long task', prdId: prd.id });
    await taskUpdate(db, { id: task.id, status: 'in_progress' });

    // Create first pause
    checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: {
        pauseReason: 'First pause',
        pausedBy: 'user'
      }
    });

    // Wait a bit
    await new Promise(resolve => setTimeout(resolve, 10));

    // Create second pause
    checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: {
        pauseReason: 'Second pause',
        pausedBy: 'user'
      }
    });

    const checkpoints = checkpointList(db, { taskId: task.id });

    // Note: taskUpdate to in_progress may auto-create a checkpoint, so we check >= 2 manual pauses
    const pauseCheckpoints = checkpoints.checkpoints.filter(
      cp => cp.trigger === 'manual' && cp.phase === 'paused'
    );
    assert(pauseCheckpoints.length === 2, `Should have 2 pause checkpoints but got ${pauseCheckpoints.length}`);

    // Pause checkpoints ordered by sequence (most recent first)
    assert(
      pauseCheckpoints[0].sequence > pauseCheckpoints[1].sequence,
      'Most recent should be first'
    );
    log('✓ Pause checkpoints ordered by recency (sequence)');

    const mostRecent = checkpointGet(db, { id: pauseCheckpoints[0].id });
    assert(mostRecent!.agentContext!.pauseReason === 'Second pause', 'Should resume most recent');
    log('✓ Most recent pause checkpoint prioritized');
  } finally {
    db.close();
  }
}

async function testContinueResumeWithFullContext(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-008', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Complex implementation', prdId: prd.id });
    await taskUpdate(db, {
      id: task.id,
      status: 'in_progress',
      notes: 'Working on authentication'
    });

    const pauseContext = {
      pauseReason: 'End of work day',
      pausedBy: 'user' as const,
      nextSteps: ['Complete JWT generation', 'Add tests'],
      keyFiles: ['src/auth/jwt.ts', 'src/auth/middleware.ts']
    };

    checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      executionStep: 3,
      agentContext: pauseContext,
      draftContent: 'function generateToken() { /* TODO */ }',
      draftType: 'implementation'
    });

    const resumed = checkpointResume(db, { taskId: task.id });

    assert(resumed !== null, 'Should resume checkpoint');
    assert(resumed!.restoredPhase === 'paused', 'Should restore phase');
    assert(resumed!.restoredStep === 3, 'Should restore step');
    assert(resumed!.hasDraft === true, 'Should indicate draft exists');
    assert(resumed!.draftType === 'implementation', 'Should restore draft type');
    assert(resumed!.agentContext !== null, 'Should restore context');
    assert(resumed!.agentContext!.pauseReason === 'End of work day', 'Reason should match');
    assert(resumed!.agentContext!.pausedBy === 'user', 'PausedBy should match');
    assert(Array.isArray(resumed!.agentContext!.nextSteps), 'NextSteps should be array');
    assert(resumed!.agentContext!.nextSteps!.length === 2, 'Should have 2 next steps');
    assert(Array.isArray(resumed!.agentContext!.keyFiles), 'KeyFiles should be array');
    assert(resumed!.agentContext!.keyFiles!.length === 2, 'Should have 2 key files');

    log('✓ Resumed from pause checkpoint');
    log(`✓ Phase: ${resumed!.restoredPhase}, Step: ${resumed!.restoredStep}`);
    log(`✓ Draft type: ${resumed!.draftType}`);
    log('✓ Full context restored');
  } finally {
    db.close();
  }
}

async function testContinueFindsPauseAcrossMultipleTasks(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-009', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });

    const task1 = await taskCreate(db, { title: 'Task 1', prdId: prd.id });
    const task2 = await taskCreate(db, { title: 'Task 2', prdId: prd.id });
    const task3 = await taskCreate(db, { title: 'Task 3', prdId: prd.id });

    await taskUpdate(db, { id: task1.id, status: 'in_progress' });
    await taskUpdate(db, { id: task2.id, status: 'in_progress' });
    await taskUpdate(db, { id: task3.id, status: 'in_progress' });

    // Pause task1 and task2
    checkpointCreate(db, {
      taskId: task1.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: { pauseReason: 'Paused task 1', pausedBy: 'user' }
    });

    checkpointCreate(db, {
      taskId: task2.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: { pauseReason: 'Paused task 2', pausedBy: 'user' }
    });

    // Auto checkpoint for task3
    checkpointCreate(db, {
      taskId: task3.id,
      trigger: 'auto_status',
      executionPhase: 'implementation'
    });

    // Find all tasks with pause checkpoints
    const allTasks = taskList(db, { status: 'in_progress' });
    const pauseCheckpoints = allTasks
      .map(task => {
        const checkpoints = checkpointList(db, { taskId: task.id });
        const pauseCp = checkpoints.checkpoints.find(
          cp => cp.trigger === 'manual' && cp.phase === 'paused'
        );
        return pauseCp ? { taskId: task.id } : null;
      })
      .filter(Boolean);

    assert(pauseCheckpoints.length === 2, 'Should find 2 paused tasks');
    assert(pauseCheckpoints.some(pc => pc!.taskId === task1.id), 'Should find task1');
    assert(pauseCheckpoints.some(pc => pc!.taskId === task2.id), 'Should find task2');
    log(`✓ Found ${pauseCheckpoints.length} tasks with pause checkpoints`);
  } finally {
    db.close();
  }
}

// ============================================================================
// TEST SUITE 3: Edge cases and validation
// ============================================================================

async function testPauseWithoutOptionalFields(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-010', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Simple task', prdId: prd.id });
    await taskUpdate(db, { id: task.id, status: 'in_progress' });

    const checkpoint = checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: {
        pauseReason: 'Quick break',
        pausedBy: 'user'
      }
    });

    const retrieved = checkpointGet(db, { id: checkpoint.id });

    assert(retrieved!.agentContext!.pauseReason === 'Quick break', 'Should have reason');
    assert(retrieved!.agentContext!.pausedBy === 'user', 'Should have pausedBy');
    assert(retrieved!.agentContext!.nextSteps === undefined, 'NextSteps should be undefined');
    assert(retrieved!.agentContext!.blockers === undefined, 'Blockers should be undefined');
    log('✓ Minimal pause checkpoint works without optional fields');
  } finally {
    db.close();
  }
}

async function testPauseTimestampAutoGenerated(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-011', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Timed task', prdId: prd.id });
    await taskUpdate(db, { id: task.id, status: 'in_progress' });

    const beforePause = new Date().toISOString();

    const checkpoint = checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      pauseMetadata: {
        pauseReason: 'Timestamp test',
        pausedBy: 'user'
      }
    });

    const afterPause = new Date().toISOString();
    const retrieved = checkpointGet(db, { id: checkpoint.id });

    assert(retrieved!.agentContext!.pausedAt !== undefined, 'Should have timestamp');

    const pausedAt = retrieved!.agentContext!.pausedAt as string;
    assert(pausedAt >= beforePause, 'Timestamp should be after start');
    assert(pausedAt <= afterPause, 'Timestamp should be before end');
    log('✓ Pause timestamp auto-generated');
  } finally {
    db.close();
  }
}

async function testSystemInitiatedPause(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-012', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Auto-paused task', prdId: prd.id });
    await taskUpdate(db, { id: task.id, status: 'in_progress' });

    const checkpoint = checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: {
        pauseReason: 'Context limit reached',
        pausedBy: 'system'
      }
    });

    const retrieved = checkpointGet(db, { id: checkpoint.id });

    assert(retrieved!.agentContext!.pausedBy === 'system', 'PausedBy should be system');
    assert(retrieved!.agentContext!.pauseReason === 'Context limit reached', 'Reason should match');
    log('✓ System-initiated pause supported');
  } finally {
    db.close();
  }
}

async function testNoCheckpointReturnsNull(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-013', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    // Don't update to in_progress - that auto-creates a checkpoint
    // Test with a pending task which should have no checkpoint
    const task = await taskCreate(db, { title: 'No checkpoint task', prdId: prd.id });

    const resumed = checkpointResume(db, { taskId: task.id });

    assert(resumed === null, 'Should return null when no checkpoint exists');
    log('✓ Resume returns null for task without checkpoint');
  } finally {
    db.close();
  }
}

async function testTaskStatusPreservation(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-014', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const task = await taskCreate(db, { title: 'Status task', prdId: prd.id });
    await taskUpdate(db, {
      id: task.id,
      status: 'in_progress',
      notes: 'Implemented half'
    });

    const checkpoint = checkpointCreate(db, {
      taskId: task.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: { pauseReason: 'Midpoint', pausedBy: 'user' }
    });

    const retrieved = checkpointGet(db, { id: checkpoint.id });

    assert(retrieved!.taskStatus === 'in_progress', 'Should preserve status');
    assert(retrieved!.taskNotes === 'Implemented half', 'Should preserve notes');
    log('✓ Task status and notes preserved in checkpoint');
  } finally {
    db.close();
  }
}

async function testSubtaskStatesCapture(): Promise<void> {
  const db = createTestDb();

  try {
    initiativeLink(db, { initiativeId: 'INIT-015', title: 'Test' });
    const prd = await prdCreate(db, { title: 'PRD', content: 'Content' });
    const parentTask = await taskCreate(db, { title: 'Parent', prdId: prd.id });
    await taskUpdate(db, { id: parentTask.id, status: 'in_progress' });

    const subtask1 = await taskCreate(db, { title: 'Subtask 1', parentId: parentTask.id });
    await taskUpdate(db, { id: subtask1.id, status: 'completed' });

    const subtask2 = await taskCreate(db, { title: 'Subtask 2', parentId: parentTask.id });
    await taskUpdate(db, { id: subtask2.id, status: 'in_progress' });

    const checkpoint = checkpointCreate(db, {
      taskId: parentTask.id,
      trigger: 'manual',
      executionPhase: 'paused',
      agentContext: { pauseReason: 'Parent paused', pausedBy: 'user' }
    });

    const retrieved = checkpointGet(db, { id: checkpoint.id });

    assert(retrieved!.subtaskStates !== undefined, 'Should have subtask states');
    assert(retrieved!.subtaskStates.length === 2, 'Should have 2 subtasks');

    const completed = retrieved!.subtaskStates.find(st => st.id === subtask1.id);
    const inProgress = retrieved!.subtaskStates.find(st => st.id === subtask2.id);

    assert(completed!.status === 'completed', 'Subtask1 should be completed');
    assert(inProgress!.status === 'in_progress', 'Subtask2 should be in_progress');
    log('✓ Subtask states captured in checkpoint');
  } finally {
    db.close();
  }
}

// ============================================================================
// MAIN TEST RUNNER
// ============================================================================

async function runAllTests(): Promise<void> {
  console.log('\n' + '='.repeat(70));
  console.log('PAUSE/RESUME CHECKPOINT TESTS');
  console.log('='.repeat(70));

  const startTime = Date.now();

  try {
    // Test Suite 1: /pause command creates checkpoint with extended expiry
    await runTest('Pause checkpoint has extended expiry', testPauseCheckpointExtendedExpiry);
    await runTest('Pause checkpoint includes reason metadata', testPauseCheckpointMetadata);
    await runTest('Pause checkpoint includes full context', testPauseCheckpointFullContext);
    await runTest('Pause creates checkpoints for multiple tasks', testPauseMultipleTasks);
    await runTest('Pause preserves draft content', testPauseDraftContent);

    // Test Suite 2: /continue detects and prioritizes pause checkpoints
    await runTest('Continue detects pause checkpoint characteristics', testContinueDetectsPauseCheckpoint);
    await runTest('Continue prioritizes most recent pause', testContinuePrioritizesMostRecentPause);
    await runTest('Continue resumes with full context', testContinueResumeWithFullContext);
    await runTest('Continue finds pauses across multiple tasks', testContinueFindsPauseAcrossMultipleTasks);

    // Test Suite 3: Edge cases and validation
    await runTest('Pause without optional fields', testPauseWithoutOptionalFields);
    await runTest('Pause timestamp auto-generated', testPauseTimestampAutoGenerated);
    await runTest('System-initiated pause', testSystemInitiatedPause);
    await runTest('No checkpoint returns null', testNoCheckpointReturnsNull);
    await runTest('Task status preservation', testTaskStatusPreservation);
    await runTest('Subtask states capture', testSubtaskStatesCapture);

    const duration = ((Date.now() - startTime) / 1000).toFixed(2);

    console.log('\n' + '='.repeat(70));
    console.log('TEST SUMMARY');
    console.log('='.repeat(70));
    console.log(`Total tests: ${testCount}`);
    console.log(`Passed: ${passCount} ✅`);
    console.log(`Failed: ${failCount} ❌`);
    console.log(`Duration: ${duration}s`);
    console.log('='.repeat(70));

    if (failCount === 0) {
      console.log('\n🎉 ALL TESTS PASSED! 🎉\n');
    } else {
      console.log('\n❌ SOME TESTS FAILED\n');
      process.exit(1);
    }
  } catch (error) {
    const duration = ((Date.now() - startTime) / 1000).toFixed(2);

    console.log('\n' + '='.repeat(70));
    console.log('TEST EXECUTION HALTED');
    console.log('='.repeat(70));
    console.log(`Tests run before failure: ${testCount}`);
    console.log(`Passed: ${passCount} ✅`);
    console.log(`Failed: ${failCount + 1} ❌`);
    console.log(`Duration: ${duration}s`);
    console.log('='.repeat(70));

    process.exit(1);
  }
}

// Auto-run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runAllTests();
}

export { runAllTests };
