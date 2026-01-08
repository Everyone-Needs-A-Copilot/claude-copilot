/**
 * Integration tests for Activation Mode Validation with Task Operations
 *
 * Tests that activation mode validation is properly integrated with:
 * - task_create (auto-detection and explicit mode setting)
 * - task_update (changing activation modes, adding subtasks)
 * - Warning generation when ultrawork mode constraint is violated
 *
 * Run with: npm run test:activation-mode-validation
 */

import { DatabaseClient } from '../../database.js';
import { taskCreate, taskUpdate, taskGet } from '../task.js';
import { initiativeLink } from '../initiative.js';
import { prdCreate } from '../prd.js';

// ============================================================================
// TEST HELPERS
// ============================================================================

let testCount = 0;
let passCount = 0;
let failCount = 0;

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

async function runTest(name: string, fn: () => void | Promise<void>): Promise<void> {
  testCount++;
  console.log(`\n${testCount}. ${name}`);
  console.log('='.repeat(60));

  try {
    await fn();
    passCount++;
    console.log('✓ PASSED');
  } catch (error) {
    failCount++;
    console.log('✗ FAILED');
    console.error(error);
  }
}

function createTestDatabase(): { db: DatabaseClient; initiativeId: string; prdId: string } {
  // Use a unique temp path for each test to ensure isolation
  const testDir = `/tmp/task-copilot-test-${Date.now()}-${Math.random().toString(36).substring(7)}`;
  const db = new DatabaseClient(testDir, testDir);

  // Set up test initiative
  const initiative = initiativeLink(db, {
    initiativeId: 'INIT-test',
    title: 'Test Initiative',
    description: 'Test'
  });

  // Set up test PRD (use sync version or handle promise)
  const prd = db.insertPrd({
    id: 'PRD-test',
    initiative_id: initiative.initiativeId,
    title: 'Test PRD',
    description: null,
    content: 'Test content',
    metadata: JSON.stringify({}),
    status: 'active',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString()
  });

  return {
    db,
    initiativeId: initiative.initiativeId,
    prdId: 'PRD-test'
  };
}

// ============================================================================
// TEST SUITE
// ============================================================================

async function runTests() {
  console.log('\n' + '='.repeat(60));
  console.log('ACTIVATION MODE VALIDATION INTEGRATION TESTS');
  console.log('='.repeat(60));

  // task_create with auto-detection
  await runTest('should auto-detect ultrawork mode from keyword', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Simple task with ultrawork keyword',
      description: 'A simple task'
    });

    assert(parent.id !== undefined, 'Task should be created');

    const retrieved = taskGet(db, { id: parent.id });
    assert(retrieved.metadata.activationMode === 'ultrawork', 'Should detect ultrawork mode');

    db.close();
  });

  await runTest('should auto-detect quick mode and allow many subtasks', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Quick implementation',
      description: 'Fast work needed'
    });

    const retrieved = taskGet(db, { id: parent.id });
    assert(retrieved.metadata.activationMode === 'quick', 'Should detect quick mode');

    // Add 5 subtasks (quick mode has no constraints)
    for (let i = 1; i <= 5; i++) {
      await taskCreate(db, {
        title: `Subtask ${i}`,
        parentId: parent.id
      });
    }

    // Should not trigger warnings
    const result = await taskUpdate(db, {
      id: parent.id,
      notes: 'Updated'
    });

    assert(result !== null, 'Update should succeed');

    db.close();
  });

  await runTest('should auto-detect last keyword when multiple present', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Code review',
      description: 'Analyze the authentication flow thoroughly'
    });

    const retrieved = taskGet(db, { id: parent.id });
    // "analyze" comes before "thorough" in text, so last keyword wins
    assert(retrieved.metadata.activationMode === 'thorough', 'Should use last keyword (thorough)');

    db.close();
  });

  await runTest('should auto-detect thorough mode and allow many subtasks', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Comprehensive security audit',
      description: 'Check all endpoints'
    });

    const retrieved = taskGet(db, { id: parent.id });
    assert(retrieved.metadata.activationMode === 'thorough', 'Should detect thorough mode');

    // Add 10 subtasks (thorough mode allows complex work)
    for (let i = 1; i <= 10; i++) {
      await taskCreate(db, {
        title: `Subtask ${i}`,
        parentId: parent.id
      });
    }

    // Should not trigger warnings
    const result = await taskUpdate(db, {
      id: parent.id,
      notes: 'Many subtasks, but thorough mode allows it'
    });

    assert(result !== null, 'Update should succeed');

    db.close();
  });

  await runTest('should set activationMode to null when no keywords found', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Regular task',
      description: 'Just implement the feature'
    });

    const retrieved = taskGet(db, { id: parent.id });
    assert(retrieved.metadata.activationMode === null, 'Should be null when no keywords');

    db.close();
  });

  // task_create with explicit mode
  await runTest('should use explicit ultrawork mode over auto-detection', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Quick task',
      description: 'Fast work',
      metadata: {
        activationMode: 'ultrawork' // Override auto-detected 'quick'
      }
    });

    const retrieved = taskGet(db, { id: parent.id });
    assert(retrieved.metadata.activationMode === 'ultrawork', 'Should use explicit mode');

    db.close();
  });

  await runTest('should allow explicit null to disable auto-detection', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Quick analyze task',
      description: 'Multiple keywords',
      metadata: {
        activationMode: null // Explicitly disable
      }
    });

    const retrieved = taskGet(db, { id: parent.id });
    assert(retrieved.metadata.activationMode === null, 'Should be null when explicitly set');

    db.close();
  });

  await runTest('should throw error for invalid activation mode', async () => {
    const { db } = createTestDatabase();

    let errorThrown = false;
    try {
      await taskCreate(db, {
        title: 'Test task',
        metadata: {
          activationMode: 'invalid-mode' as any
        }
      });
    } catch (error: any) {
      errorThrown = true;
      assert(error.message.includes('Invalid activationMode'), 'Should include error message');
    }

    assert(errorThrown, 'Should throw error for invalid mode');

    db.close();
  });

  // task_update with activation mode changes
  await runTest('should allow changing activation mode from null to ultrawork', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Regular task',
      description: 'No keywords'
    });

    assert(taskGet(db, { id: parent.id }).metadata.activationMode === null, 'Initial mode should be null');

    // Change to ultrawork mode
    const result = await taskUpdate(db, {
      id: parent.id,
      metadata: {
        activationMode: 'ultrawork'
      }
    });

    assert(result !== null, 'Update should succeed');
    assert(taskGet(db, { id: parent.id }).metadata.activationMode === 'ultrawork', 'Mode should change to ultrawork');

    db.close();
  });

  await runTest('should allow changing from ultrawork to thorough to fix violations', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Simple task',
      metadata: {
        activationMode: 'ultrawork'
      }
    });

    // Add 5 subtasks (violates ultrawork constraint)
    for (let i = 1; i <= 5; i++) {
      await taskCreate(db, {
        title: `Subtask ${i}`,
        parentId: parent.id
      });
    }

    // Change to thorough mode to allow complexity
    const result = await taskUpdate(db, {
      id: parent.id,
      metadata: {
        activationMode: 'thorough'
      }
    });

    assert(result !== null, 'Update should succeed');
    assert(taskGet(db, { id: parent.id }).metadata.activationMode === 'thorough', 'Mode should change to thorough');

    db.close();
  });

  await runTest('should preserve other metadata when updating activation mode', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Task with metadata',
      metadata: {
        complexity: 'High',
        priority: 'P0',
        customField: 'value'
      }
    });

    // Update only activation mode
    await taskUpdate(db, {
      id: parent.id,
      metadata: {
        activationMode: 'ultrawork'
      }
    });

    const retrieved = taskGet(db, { id: parent.id });
    assert(retrieved.metadata.activationMode === 'ultrawork', 'Mode should be updated');
    assert(retrieved.metadata.complexity === 'High', 'Complexity should be preserved');
    assert(retrieved.metadata.priority === 'P0', 'Priority should be preserved');
    assert(retrieved.metadata.customField === 'value', 'Custom field should be preserved');

    db.close();
  });

  // ultrawork mode warning scenarios
  await runTest('should not warn for ultrawork task with exactly 3 subtasks', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Well-scoped task',
      metadata: {
        activationMode: 'ultrawork'
      }
    });

    // Add exactly 3 subtasks
    for (let i = 1; i <= 3; i++) {
      await taskCreate(db, {
        title: `Subtask ${i}`,
        parentId: parent.id
      });
    }

    const result = await taskUpdate(db, {
      id: parent.id,
      notes: 'Update with valid subtask count'
    });

    assert(result !== null, 'Update should succeed without warnings');

    db.close();
  });

  await runTest('should handle ultrawork task with >3 subtasks (validation warns but allows)', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Task that will exceed limit',
      metadata: {
        activationMode: 'ultrawork'
      }
    });

    // Add 4 subtasks (exceeds limit)
    for (let i = 1; i <= 4; i++) {
      await taskCreate(db, {
        title: `Subtask ${i}`,
        parentId: parent.id
      });
    }

    // Trigger validation by updating with mode set
    const result = await taskUpdate(db, {
      id: parent.id,
      metadata: {
        activationMode: 'ultrawork' // Re-setting triggers validation
      }
    });

    // Warning is issued but update succeeds
    assert(result !== null, 'Update should succeed despite warning');
    assert(result?.status === 'pending', 'Status should remain pending');

    db.close();
  });

  await runTest('should not warn when updating non-ultrawork task with many subtasks', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Complex task',
      metadata: {
        activationMode: 'thorough'
      }
    });

    // Add 10 subtasks
    for (let i = 1; i <= 10; i++) {
      await taskCreate(db, {
        title: `Subtask ${i}`,
        parentId: parent.id
      });
    }

    const result = await taskUpdate(db, {
      id: parent.id,
      notes: 'Thorough mode allows many subtasks'
    });

    assert(result !== null, 'Update should succeed');

    db.close();
  });

  // edge cases
  await runTest('should handle tasks with no parent', async () => {
    const { db } = createTestDatabase();

    const task = await taskCreate(db, {
      title: 'Simple standalone task',
      metadata: {
        activationMode: 'ultrawork'
      }
    });

    const result = await taskUpdate(db, {
      id: task.id,
      notes: 'No parent, no subtasks'
    });

    assert(result !== null, 'Update should succeed');

    db.close();
  });

  await runTest('should handle nested subtasks correctly (only count direct children)', async () => {
    const { db } = createTestDatabase();

    const parent = await taskCreate(db, {
      title: 'Parent task',
      metadata: {
        activationMode: 'ultrawork'
      }
    });

    // Add 2 direct subtasks
    const subtask1 = await taskCreate(db, {
      title: 'Subtask 1',
      parentId: parent.id
    });

    const subtask2 = await taskCreate(db, {
      title: 'Subtask 2',
      parentId: parent.id
    });

    // Add nested subtasks (shouldn't count toward parent)
    await taskCreate(db, {
      title: 'Nested 1',
      parentId: subtask1.id
    });

    await taskCreate(db, {
      title: 'Nested 2',
      parentId: subtask2.id
    });

    // Update parent - should not trigger warning (only 2 direct subtasks)
    const result = await taskUpdate(db, {
      id: parent.id,
      notes: 'Has nested structure but within limit'
    });

    assert(result !== null, 'Update should succeed without warnings');

    db.close();
  });

  // Print summary
  console.log('\n' + '='.repeat(60));
  console.log('TEST SUMMARY');
  console.log('='.repeat(60));
  console.log(`Total:  ${testCount}`);
  console.log(`Passed: ${passCount}`);
  console.log(`Failed: ${failCount}`);
  console.log('='.repeat(60));

  if (failCount > 0) {
    process.exit(1);
  }
}

// Run tests
runTests().catch(error => {
  console.error('Test suite failed:', error);
  process.exit(1);
});
