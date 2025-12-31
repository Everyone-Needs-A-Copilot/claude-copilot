/**
 * Tests for iteration metrics in agent performance tracking
 *
 * Run with: npm test (if configured) or manually validate
 */

import { DatabaseClient } from '../database.js';
import { agentPerformanceGet } from './performance.js';
import { iterationStart, iterationNext, iterationComplete } from './iteration.js';
import { taskCreate } from './task.js';
import { tmpdir } from 'os';
import { join } from 'path';
import { mkdirSync, rmSync } from 'fs';

/**
 * Integration test for iteration metrics
 */
async function testIterationMetrics() {
  console.log('Starting iteration metrics test...\n');

  // Create temporary database
  const testDir = join(tmpdir(), `task-copilot-test-${Date.now()}`);
  mkdirSync(testDir, { recursive: true });

  const db = new DatabaseClient(testDir, testDir, 'test-workspace');

  try {
    // Link initiative
    db.upsertInitiative({
      id: 'TEST-INIT-001',
      title: 'Test Initiative',
      description: 'Testing iteration metrics',
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString()
    });

    // Create test tasks for agent "me"
    console.log('Creating test tasks...');
    const task1 = await taskCreate(db, {
      title: 'Task 1: Complete in 2 iterations',
      assignedAgent: 'me',
      metadata: { complexity: 'medium' }
    });

    const task2 = await taskCreate(db, {
      title: 'Task 2: Complete in 4 iterations',
      assignedAgent: 'me',
      metadata: { complexity: 'high' }
    });

    const task3 = await taskCreate(db, {
      title: 'Task 3: Hit max iterations',
      assignedAgent: 'me',
      metadata: { complexity: 'high' }
    });

    console.log(`Created tasks: ${task1.id}, ${task2.id}, ${task3.id}\n`);

    // Simulate iteration session 1: Complete in 2 iterations
    console.log('Simulating iteration session 1 (2 iterations to completion)...');
    const iter1 = iterationStart(db, {
      taskId: task1.id,
      maxIterations: 5,
      completionPromises: ['All tests pass', 'Code reviewed']
    });

    const iter1Next = iterationNext(db, {
      iterationId: iter1.iterationId,
      validationResult: {
        passed: false,
        flags: [{ ruleId: 'test', message: 'First attempt failed', severity: 'warn' }]
      }
    });

    iterationComplete(db, {
      iterationId: iter1.iterationId,
      completionPromise: 'All tests pass'
    });

    console.log(`  Completed in ${iter1Next.iterationNumber} iterations\n`);

    // Simulate iteration session 2: Complete in 4 iterations with regression
    console.log('Simulating iteration session 2 (4 iterations with regression)...');
    const iter2 = iterationStart(db, {
      taskId: task2.id,
      maxIterations: 10,
      completionPromises: ['Implementation complete', 'Tests added'],
      circuitBreakerThreshold: 3
    });

    // Iteration 1: fail
    iterationNext(db, {
      iterationId: iter2.iterationId,
      validationResult: {
        passed: false,
        flags: [{ ruleId: 'lint', message: 'Linting errors', severity: 'reject' }]
      }
    });

    // Iteration 2: pass
    iterationNext(db, {
      iterationId: iter2.iterationId,
      validationResult: {
        passed: true,
        flags: []
      }
    });

    // Iteration 3: fail (regression!)
    iterationNext(db, {
      iterationId: iter2.iterationId,
      validationResult: {
        passed: false,
        flags: [{ ruleId: 'test', message: 'Tests broken', severity: 'reject' }]
      }
    });

    // Iteration 4: complete
    iterationComplete(db, {
      iterationId: iter2.iterationId,
      completionPromise: 'Implementation complete'
    });

    console.log('  Completed in 4 iterations (with quality regression pattern)\n');

    // Simulate iteration session 3: Hit max iterations
    console.log('Simulating iteration session 3 (max iterations reached)...');
    const iter3 = iterationStart(db, {
      taskId: task3.id,
      maxIterations: 3,
      completionPromises: ['Complex task done'],
      circuitBreakerThreshold: 2
    });

    // Iteration 1: fail
    iterationNext(db, {
      iterationId: iter3.iterationId,
      validationResult: {
        passed: false,
        flags: [{ ruleId: 'validation', message: 'Failed', severity: 'reject' }]
      }
    });

    // Iteration 2: fail (circuit breaker should trigger after this)
    iterationNext(db, {
      iterationId: iter3.iterationId,
      validationResult: {
        passed: false,
        flags: [{ ruleId: 'validation', message: 'Failed again', severity: 'reject' }]
      }
    });

    // This would hit max iterations (3), so we stop here
    console.log('  Reached max iterations (3)\n');

    // Get performance metrics
    console.log('Querying agent performance metrics...');
    const performance = agentPerformanceGet(db, {
      agentId: 'me'
    });

    console.log('\n=== PERFORMANCE RESULTS ===\n');
    console.log(JSON.stringify(performance, null, 2));

    // Validate iteration metrics exist
    const agent = performance.agents.find(a => a.agentId === 'me');
    if (!agent) {
      throw new Error('Agent "me" not found in performance results');
    }

    if (!agent.iterationMetrics) {
      throw new Error('Iteration metrics missing for agent "me"');
    }

    console.log('\n=== ITERATION METRICS VALIDATION ===\n');

    const metrics = agent.iterationMetrics;

    // Validate metrics
    const validations = [
      { name: 'Total sessions', actual: metrics.totalIterationSessions, expected: 3 },
      { name: 'Completed sessions', actual: metrics.totalIterationSessions - (metrics.safetyGuardTriggers.maxIterations || 0), expected: 2 },
      { name: 'Has quality regression', actual: metrics.safetyGuardTriggers.qualityRegression > 0, expected: true },
      { name: 'Has max iterations trigger', actual: metrics.safetyGuardTriggers.maxIterations > 0, expected: true },
      { name: 'Has circuit breaker data', actual: metrics.safetyGuardTriggers.circuitBreaker >= 0, expected: true }
    ];

    let allPassed = true;
    for (const check of validations) {
      const passed = check.actual === check.expected;
      allPassed = allPassed && passed;
      console.log(`${passed ? '✓' : '✗'} ${check.name}: ${check.actual} ${passed ? '==' : '!='} ${check.expected}`);
    }

    console.log('\n=== TEST SUMMARY ===\n');
    if (allPassed) {
      console.log('✓ All tests PASSED');
    } else {
      console.log('✗ Some tests FAILED');
    }

  } finally {
    // Cleanup
    db.close();
    rmSync(testDir, { recursive: true, force: true });
    console.log('\nTest database cleaned up.');
  }
}

// Run test if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  testIterationMetrics().catch(error => {
    console.error('Test failed:', error);
    process.exit(1);
  });
}

export { testIterationMetrics };
