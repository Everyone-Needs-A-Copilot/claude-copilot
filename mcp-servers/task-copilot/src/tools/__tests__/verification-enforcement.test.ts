/**
 * Test verification enforcement feature
 *
 * Tests:
 * 1. Validation rule for acceptanceCriteria (tasks with verificationRequired should have acceptance criteria)
 * 2. Proof validation for task completion (completion should include proof when required)
 * 3. task_update blocking completion when verification is required but not provided
 * 4. Various proof types (work products, notes, blocked reason)
 * 5. Edge cases and error messages
 */

import { DatabaseClient } from '../../database.js';
import { taskCreate, taskUpdate, taskGet } from '../task.js';
import { workProductStore } from '../work-product.js';
import { initiativeLink } from '../initiative.js';
import { prdCreate } from '../prd.js';
import type { TaskCreateInput, TaskUpdateInput, WorkProductStoreInput } from '../../types.js';
import { mkdirSync, rmSync } from 'fs';
import { join } from 'path';
import { tmpdir } from 'os';

function createTestDatabase(): DatabaseClient {
  const testDir = join(tmpdir(), `verification-enforcement-test-${Date.now()}`);
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
  console.log('🧪 Testing Verification Enforcement Feature\n');

  let testCount = 0;
  let passCount = 0;
  let failCount = 0;

  // ========================================
  // ACCEPTANCE CRITERIA VALIDATION
  // ========================================

  // Test 1: Task with verificationRequired must have acceptance criteria
  testCount++;
  console.log(`Test ${testCount}: Task with verificationRequired=true requires acceptance criteria`);
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
      title: 'Task Without Acceptance Criteria',
      metadata: {
        verificationRequired: true
        // No acceptanceCriteria provided
      }
    };

    const task = await taskCreate(db, input);

    // Try to complete - should fail
    let errorThrown = false;
    try {
      await taskUpdate(db, {
        id: task.id,
        status: 'completed'
      });
    } catch (error) {
      errorThrown = true;
      assert(error instanceof Error, 'Error should be Error instance');
      assert(error.message.includes('acceptance criteria') || error.message.includes('ACCEPTANCE_CRITERIA'),
        'Error should mention acceptance criteria');
      assert(error.message.includes('verificationRequired'),
        'Error should mention verificationRequired');
    }

    assert(errorThrown, 'Should throw error when completing without acceptance criteria');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 2: Empty acceptance criteria array should fail
  testCount++;
  console.log(`Test ${testCount}: Empty acceptanceCriteria array should fail verification`);
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
      title: 'Task With Empty Acceptance Criteria',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: [] // Empty array
      }
    };

    const task = await taskCreate(db, input);

    // Try to complete - should fail
    let errorThrown = false;
    try {
      await taskUpdate(db, {
        id: task.id,
        status: 'completed'
      });
    } catch (error) {
      errorThrown = true;
      assert(error instanceof Error, 'Error should be Error instance');
      assert(error.message.includes('acceptance criteria'),
        'Error should mention acceptance criteria');
    }

    assert(errorThrown, 'Should throw error when acceptanceCriteria is empty');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 3: Valid acceptance criteria should pass first check
  testCount++;
  console.log(`Test ${testCount}: Valid acceptanceCriteria passes acceptance criteria check`);
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
      title: 'Task With Valid Acceptance Criteria',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Tests pass', 'Code reviewed']
      }
    };

    const task = await taskCreate(db, input);

    // Try to complete - should fail on proof requirement, NOT acceptance criteria
    let errorThrown = false;
    let errorMessage = '';
    try {
      await taskUpdate(db, {
        id: task.id,
        status: 'completed'
      });
    } catch (error) {
      errorThrown = true;
      errorMessage = error instanceof Error ? error.message : String(error);
      // Should fail on proof, not acceptance criteria
      assert(errorMessage.includes('proof') || errorMessage.includes('evidence'),
        'Error should mention proof/evidence');
      assert(!errorMessage.includes('[ACCEPTANCE_CRITERIA]'),
        'Error should not include ACCEPTANCE_CRITERIA flag when acceptance criteria are provided');
    }

    assert(errorThrown, 'Should throw error for missing proof (but not acceptance criteria)');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // ========================================
  // PROOF VALIDATION - WORK PRODUCTS
  // ========================================

  // Test 4: Work product as proof should allow completion
  testCount++;
  console.log(`Test ${testCount}: Work product as proof allows completion`);
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
      title: 'Task With Work Product Proof',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Tests pass']
      }
    };

    const task = await taskCreate(db, input);

    // Add work product as proof
    const wpInput: WorkProductStoreInput = {
      taskId: task.id,
      type: 'implementation',
      title: 'Implementation with tests',
      content: 'Implemented feature X with passing tests'
    };
    await workProductStore(db, wpInput);

    // Now completion should succeed
    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'completed', 'Task should be completed');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 5: Multiple work products should also count as proof
  testCount++;
  console.log(`Test ${testCount}: Multiple work products count as proof`);
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
      title: 'Task With Multiple Work Products',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Implementation complete', 'Tests added']
      }
    };

    const task = await taskCreate(db, input);

    // Add multiple work products
    await workProductStore(db, {
      taskId: task.id,
      type: 'implementation',
      title: 'Code implementation',
      content: 'Implemented feature'
    });

    await workProductStore(db, {
      taskId: task.id,
      type: 'test_plan',
      title: 'Test plan',
      content: 'Added tests for feature'
    });

    // Completion should succeed
    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'completed', 'Task should be completed');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // ========================================
  // PROOF VALIDATION - NOTES
  // ========================================

  // Test 6: Substantive notes (>50 chars) as proof should allow completion
  testCount++;
  console.log(`Test ${testCount}: Substantive notes (>50 chars) as proof allow completion`);
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
      title: 'Task With Notes Proof',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Feature works correctly']
      }
    };

    const task = await taskCreate(db, input);

    // Add substantive notes (>50 chars)
    const notes = 'All acceptance criteria met. Tests passing. Screenshot at /tmp/test.png. Ready for review.';

    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'completed',
      notes
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'completed', 'Task should be completed');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 7: Notes with exactly 50 chars should count as proof
  testCount++;
  console.log(`Test ${testCount}: Notes with exactly 50 chars count as proof`);
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
      title: 'Task With 50-char Notes',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Done']
      }
    };

    const task = await taskCreate(db, input);

    // Exactly 50 chars
    const notes = '12345678901234567890123456789012345678901234567890'; // 50 chars

    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'completed',
      notes
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'completed', 'Task should be completed with exactly 50 chars');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 8: Notes with 49 chars should NOT count as proof
  testCount++;
  console.log(`Test ${testCount}: Notes with 49 chars should NOT count as proof`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-008',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task With 49-char Notes',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Done']
      }
    };

    const task = await taskCreate(db, input);

    // Only 49 chars
    const notes = '1234567890123456789012345678901234567890123456789'; // 49 chars

    let errorThrown = false;
    try {
      await taskUpdate(db, {
        id: task.id,
        status: 'completed',
        notes
      });
    } catch (error) {
      errorThrown = true;
      assert(error instanceof Error, 'Error should be Error instance');
      assert(error.message.includes('proof') || error.message.includes('evidence'),
        'Error should mention proof/evidence requirement');
    }

    assert(errorThrown, 'Should throw error when notes are less than 50 chars');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 9: Very short notes should fail
  testCount++;
  console.log(`Test ${testCount}: Very short notes should fail verification`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-009',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task With Short Notes',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Done']
      }
    };

    const task = await taskCreate(db, input);

    let errorThrown = false;
    try {
      await taskUpdate(db, {
        id: task.id,
        status: 'completed',
        notes: 'Done' // Only 4 chars
      });
    } catch (error) {
      errorThrown = true;
      assert(error instanceof Error, 'Error should be Error instance');
      assert(error.message.includes('proof') || error.message.includes('evidence'),
        'Error should mention proof requirement');
    }

    assert(errorThrown, 'Should throw error for very short notes');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // ========================================
  // PROOF VALIDATION - BLOCKED REASON
  // ========================================

  // Test 10: Blocked reason counts as proof
  testCount++;
  console.log(`Test ${testCount}: Blocked reason counts as valid proof`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-010',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task That Will Be Blocked',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Feature works']
      }
    };

    const task = await taskCreate(db, input);

    // Mark as blocked with reason - should count as proof
    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'blocked',
      blockedReason: 'Waiting for API endpoint to be deployed'
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'blocked', 'Task should be blocked');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 11: Completing with blocked reason previously set should still work
  testCount++;
  console.log(`Test ${testCount}: Completion allowed when task has blockedReason from previous update`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-011',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task Previously Blocked',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Feature complete']
      }
    };

    const task = await taskCreate(db, input);

    // First, mark as blocked
    await taskUpdate(db, {
      id: task.id,
      status: 'blocked',
      blockedReason: 'Was waiting for dependencies'
    });

    // Now complete - blocked reason should count as proof
    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'completed', 'Task should be completed');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // ========================================
  // TASK_UPDATE BLOCKING
  // ========================================

  // Test 12: task_update blocks completion when both criteria and proof missing
  testCount++;
  console.log(`Test ${testCount}: task_update blocks completion when both criteria and proof missing`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-012',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task Without Criteria or Proof',
      metadata: {
        verificationRequired: true
      }
    };

    const task = await taskCreate(db, input);

    let errorThrown = false;
    let errorMessage = '';
    try {
      await taskUpdate(db, {
        id: task.id,
        status: 'completed'
      });
    } catch (error) {
      errorThrown = true;
      errorMessage = error instanceof Error ? error.message : String(error);
      // Should mention both issues
      assert(errorMessage.includes('acceptance criteria') || errorMessage.includes('ACCEPTANCE_CRITERIA'),
        'Error should mention acceptance criteria');
    }

    assert(errorThrown, 'Should throw error when both criteria and proof are missing');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 13: task_update allows update to non-completed status without verification
  testCount++;
  console.log(`Test ${testCount}: task_update allows status changes to non-completed without verification`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-013',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task To Mark In Progress',
      metadata: {
        verificationRequired: true
        // No criteria or proof
      }
    };

    const task = await taskCreate(db, input);

    // Update to in_progress should work without verification
    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'in_progress'
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'in_progress', 'Task should be in_progress');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 14: task_update allows field updates without status change
  testCount++;
  console.log(`Test ${testCount}: task_update allows field updates without completion`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-014',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task To Update',
      metadata: {
        verificationRequired: true
      }
    };

    const task = await taskCreate(db, input);

    // Update notes without changing status
    const updated = await taskUpdate(db, {
      id: task.id,
      notes: 'Work in progress'
    });

    assert(updated !== null, 'Task should be updated');

    // Verify notes were actually updated in database
    const updatedTask = taskGet(db, { id: task.id });
    assert(updatedTask !== null, 'Task should exist');
    assert(updatedTask.notes === 'Work in progress', 'Notes should be updated');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // ========================================
  // ERROR MESSAGES AND SUGGESTIONS
  // ========================================

  // Test 15: Error message should include suggestions
  testCount++;
  console.log(`Test ${testCount}: Error message includes actionable suggestions`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-015',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task To Check Error Message',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Requirement met']
      }
    };

    const task = await taskCreate(db, input);

    let errorMessage = '';
    try {
      await taskUpdate(db, {
        id: task.id,
        status: 'completed'
      });
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : String(error);
    }

    // Check for helpful suggestions in error message
    assert(errorMessage.includes('work_product_store') ||
           errorMessage.includes('notes') ||
           errorMessage.includes('suggestion'),
      'Error should include suggestions on how to fix');
    assert(errorMessage.includes('min 50 chars') || errorMessage.includes('50'),
      'Error should mention minimum character requirement for notes');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 16: Error message should mention how to disable verification
  testCount++;
  console.log(`Test ${testCount}: Error message mentions how to disable verification`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-016',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task To Check Disable Message',
      metadata: {
        verificationRequired: true
      }
    };

    const task = await taskCreate(db, input);

    let errorMessage = '';
    try {
      await taskUpdate(db, {
        id: task.id,
        status: 'completed'
      });
    } catch (error) {
      errorMessage = error instanceof Error ? error.message : String(error);
    }

    assert(errorMessage.includes('verificationRequired=false') ||
           errorMessage.includes('disable'),
      'Error should mention how to disable verification');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // ========================================
  // EDGE CASES
  // ========================================

  // Test 17: Task without verificationRequired should complete without verification
  testCount++;
  console.log(`Test ${testCount}: Task without verificationRequired bypasses verification`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-017',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task Without Verification',
      metadata: {
        // No verificationRequired
      }
    };

    const task = await taskCreate(db, input);

    // Should complete without any criteria or proof
    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'completed', 'Task should be completed without verification');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 18: Task with verificationRequired=false should complete without verification
  testCount++;
  console.log(`Test ${testCount}: Task with verificationRequired=false bypasses verification`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-018',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task With Verification Disabled',
      metadata: {
        verificationRequired: false
      }
    };

    const task = await taskCreate(db, input);

    // Should complete without any criteria or proof
    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'completed'
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'completed', 'Task should be completed with verification disabled');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 19: Whitespace-only notes should not count as proof
  testCount++;
  console.log(`Test ${testCount}: Whitespace-only notes should not count as proof`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-019',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task With Whitespace Notes',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Done']
      }
    };

    const task = await taskCreate(db, input);

    let errorThrown = false;
    try {
      // 60 spaces - should be trimmed to 0
      await taskUpdate(db, {
        id: task.id,
        status: 'completed',
        notes: '                                                            '
      });
    } catch (error) {
      errorThrown = true;
      assert(error instanceof Error, 'Error should be Error instance');
      assert(error.message.includes('proof') || error.message.includes('evidence'),
        'Error should mention proof requirement');
    }

    assert(errorThrown, 'Should throw error for whitespace-only notes');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 20: Combination - work product added, then update notes and complete
  testCount++;
  console.log(`Test ${testCount}: Combination of work product and notes update works`);
  try {
    const db = createTestDatabase();
    initiativeLink(db, {
      initiativeId: 'INIT-TEST-020',
      title: 'Test Initiative'
    });

    const prd = await prdCreate(db, {
      title: 'Test PRD',
      content: 'Test content',
      metadata: {}
    });

    const input: TaskCreateInput = {
      prdId: prd.id,
      title: 'Task With Combination Proof',
      metadata: {
        verificationRequired: true,
        acceptanceCriteria: ['Feature complete', 'Tests added']
      }
    };

    const task = await taskCreate(db, input);

    // Add work product
    await workProductStore(db, {
      taskId: task.id,
      type: 'implementation',
      title: 'Implementation',
      content: 'Feature implemented'
    });

    // Complete with notes (even though work product is already enough)
    const updated = await taskUpdate(db, {
      id: task.id,
      status: 'completed',
      notes: 'All acceptance criteria verified. Work product attached with full implementation.'
    });

    assert(updated !== null, 'Task should be updated');
    assert(updated.status === 'completed', 'Task should be completed');

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
