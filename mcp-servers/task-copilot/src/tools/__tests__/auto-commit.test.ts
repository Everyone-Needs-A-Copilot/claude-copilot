/**
 * Test auto-commit on task completion
 *
 * Verifies:
 * 1. task_update returns autoCommitRequested flag when autoCommitOnComplete is true
 * 2. Flag only returned on transition TO completed (not when already completed)
 * 3. Suggested commit message format is correct
 * 4. Default behavior is opt-in (no flag when autoCommitOnComplete is not set)
 */

import { DatabaseClient } from '../../database.js';
import { taskCreate, taskUpdate, taskGet } from '../task.js';
import { initiativeLink } from '../initiative.js';
import { prdCreate } from '../prd.js';
import type { TaskCreateInput, TaskUpdateInput } from '../../types.js';
import { mkdirSync, rmSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

function createTestDatabase(): DatabaseClient {
  const testDir = join(tmpdir(), `auto-commit-test-${Date.now()}`);
  mkdirSync(testDir, { recursive: true });

  const db = new DatabaseClient(
    '/test/project',
    testDir,
    `test-${Date.now()}`
  );

  return db;
}

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

async function runTests() {
  console.log('🧪 Testing Auto-Commit on Task Completion\n');

  let testCount = 0;
  let passCount = 0;
  let failCount = 0;

  // Test 1: Auto-commit flag returned when autoCommitOnComplete is true
  testCount++;
  console.log(`Test ${testCount}: Auto-commit flag returned when enabled`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-001',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Implement user authentication',
      metadata: {
        autoCommitOnComplete: true,
        filesModified: ['src/auth/login.ts', 'src/auth/login.test.ts']
      }
    };

    const task = await taskCreate(db, input);

    // Complete the task
    const result = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(result !== null, 'Update result should not be null');
    assert(result.autoCommitRequested === true, 'autoCommitRequested should be true');
    assert(result.suggestedCommitMessage !== undefined, 'suggestedCommitMessage should be provided');
    assert(
      result.suggestedCommitMessage === `feat(${task.id}): Implement user authentication`,
      'Commit message format should be correct'
    );

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 2: No flag when autoCommitOnComplete is false (default)
  testCount++;
  console.log(`Test ${testCount}: No auto-commit flag when disabled (default)`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-002',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Update documentation',
      metadata: {
        filesModified: ['README.md']
        // autoCommitOnComplete not set (defaults to false)
      }
    };

    const task = await taskCreate(db, input);

    // Complete the task
    const result = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(result !== null, 'Update result should not be null');
    assert(result.autoCommitRequested === undefined, 'autoCommitRequested should not be set');
    assert(result.suggestedCommitMessage === undefined, 'suggestedCommitMessage should not be set');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 3: No flag when task is already completed (no transition)
  testCount++;
  console.log(`Test ${testCount}: No auto-commit flag when task already completed`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-003',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Fix bug',
      metadata: {
        autoCommitOnComplete: true,
        filesModified: ['src/bug-fix.ts']
      }
    };

    const task = await taskCreate(db, input);

    // Complete the task first time
    await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    // Try to update the already completed task
    const result = await taskUpdate(db, {
      id: task.id,
      status: 'completed',
      notes: 'Additional notes'
    });

    assert(result !== null, 'Update result should not be null');
    assert(result.autoCommitRequested === undefined, 'autoCommitRequested should not be set for already completed task');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 4: Commit message format with special characters
  testCount++;
  console.log(`Test ${testCount}: Commit message format with special characters`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-004',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Add "dark mode" & <special> chars',
      metadata: {
        autoCommitOnComplete: true
      }
    };

    const task = await taskCreate(db, input);

    // Complete the task
    const result = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(result !== null, 'Update result should not be null');
    assert(result.autoCommitRequested === true, 'autoCommitRequested should be true');
    assert(result.suggestedCommitMessage !== undefined, 'suggestedCommitMessage should be provided');
    assert(
      result.suggestedCommitMessage.includes(task.id),
      'Commit message should include task ID'
    );
    assert(
      result.suggestedCommitMessage.includes('Add "dark mode" & <special> chars'),
      'Commit message should include task title with special chars'
    );

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 5: Enable auto-commit via task_update
  testCount++;
  console.log(`Test ${testCount}: Enable auto-commit via task_update metadata`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-005',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Add feature',
      metadata: {
        // No autoCommitOnComplete initially
        filesModified: ['src/feature.ts']
      }
    };

    const task = await taskCreate(db, input);

    // Enable auto-commit and complete in same update
    const result = await taskUpdate(db, {
      id: task.id,
      status: 'completed',
      metadata: {
        autoCommitOnComplete: true
      }
    });

    assert(result !== null, 'Update result should not be null');
    assert(result.autoCommitRequested === true, 'autoCommitRequested should be true when enabled via update');
    assert(result.suggestedCommitMessage !== undefined, 'suggestedCommitMessage should be provided');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 6: Auto-commit with status transition from blocked to completed
  testCount++;
  console.log(`Test ${testCount}: Auto-commit works when transitioning from blocked to completed`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-006',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Previously blocked task',
      metadata: {
        autoCommitOnComplete: true,
        filesModified: ['src/fix.ts']
      }
    };

    const task = await taskCreate(db, input);

    // First block the task
    await taskUpdate(db, {
      id: task.id,
      status: 'blocked',
      blockedReason: 'Waiting for dependency'
    });

    // Now complete it
    const result = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(result !== null, 'Update result should not be null');
    assert(result.autoCommitRequested === true, 'autoCommitRequested should be true when transitioning from blocked');
    assert(result.suggestedCommitMessage !== undefined, 'suggestedCommitMessage should be provided');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 7: Explicit autoCommitOnComplete=false prevents flag
  testCount++;
  console.log(`Test ${testCount}: Explicit false prevents auto-commit flag`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-007',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Manual commit task',
      metadata: {
        autoCommitOnComplete: false, // Explicitly disabled
        filesModified: ['src/manual.ts']
      }
    };

    const task = await taskCreate(db, input);

    // Complete the task
    const result = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(result !== null, 'Update result should not be null');
    assert(result.autoCommitRequested === undefined, 'autoCommitRequested should not be set when explicitly disabled');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Print summary
  console.log('\n' + '='.repeat(60));
  console.log('📊 Test Summary');
  console.log('='.repeat(60));
  console.log(`Total Tests: ${testCount}`);
  console.log(`✅ Passed: ${passCount}`);
  console.log(`❌ Failed: ${failCount}`);
  console.log(`Success Rate: ${((passCount / testCount) * 100).toFixed(1)}%`);

  if (failCount === 0) {
    console.log('\n🎉 All tests passed!');
    process.exit(0);
  } else {
    console.log('\n⚠️  Some tests failed');
    process.exit(1);
  }
}

runTests().catch(error => {
  console.error('Fatal error running tests:', error);
  process.exit(1);
});
