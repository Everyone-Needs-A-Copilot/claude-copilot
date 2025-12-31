/**
 * Tests for iteration safety guards
 *
 * Run with: node --loader ts-node/esm iteration-guards.test.ts
 * Or integrate into your test framework
 */

import {
  checkMaxIterations,
  checkQualityRegression,
  checkThrashing,
  checkCircuitBreaker,
  runSafetyChecks
} from './iteration-guards.js';
import type { IterationConfig, IterationHistoryEntry } from '../types.js';

// ============================================================================
// TEST HELPERS
// ============================================================================

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

function createHistoryEntry(
  iteration: number,
  passed: boolean,
  flags: Array<{ ruleId: string; message: string; severity: string }> = []
): IterationHistoryEntry {
  return {
    iteration,
    timestamp: new Date().toISOString(),
    validationResult: { passed, flags },
    checkpointId: `CP-${iteration}`
  };
}

// ============================================================================
// TEST SUITE
// ============================================================================

function testMaxIterations(): void {
  console.log('Testing checkMaxIterations...');

  // Within limit
  let result = checkMaxIterations(3, 5);
  assert(result.allowed === true, 'Should allow iteration 3 of 5');

  // At limit
  result = checkMaxIterations(5, 5);
  assert(result.allowed === true, 'Should allow iteration 5 of 5');

  // Exceeds limit
  result = checkMaxIterations(6, 5);
  assert(result.allowed === false, 'Should block iteration 6 of 5');
  assert(result.message && result.message.includes('exceeds maximum'), 'Should have descriptive message');

  console.log('  ✓ All max iterations tests passed');
}

function testQualityRegression(): void {
  console.log('Testing checkQualityRegression...');

  // Not enough data
  let history = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, true)
  ];
  let result = checkQualityRegression(history);
  assert(result.regression === false, 'Should not detect regression with insufficient data');

  // No regression - all passing
  history = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, true),
    createHistoryEntry(3, true)
  ];
  result = checkQualityRegression(history);
  assert(result.regression === false, 'Should not detect regression when all passing');

  // No regression - improving
  history = [
    createHistoryEntry(1, false),
    createHistoryEntry(2, false),
    createHistoryEntry(3, true)
  ];
  result = checkQualityRegression(history);
  assert(result.regression === false, 'Should not detect regression when improving');

  // Regression detected - 3 consecutive declines
  history = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, false),
    createHistoryEntry(3, false),
    createHistoryEntry(4, false)
  ];
  result = checkQualityRegression(history);
  assert(result.regression === true, 'Should detect regression with 3 consecutive declines');
  assert(result.consecutiveDeclines === 2, 'Should count 2 consecutive declines');
  assert(result.message && result.message.includes('regression'), 'Should have descriptive message');

  // Regression reset by improvement
  history = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, false),
    createHistoryEntry(3, false),
    createHistoryEntry(4, true),
    createHistoryEntry(5, false)
  ];
  result = checkQualityRegression(history);
  assert(result.regression === false, 'Should reset regression counter on improvement');

  console.log('  ✓ All quality regression tests passed');
}

function testThrashing(): void {
  console.log('Testing checkThrashing...');

  // Not enough iterations
  let history = [
    createHistoryEntry(1, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }])
  ];
  let result = checkThrashing(history);
  assert(result.thrashing === false, 'Should not detect thrashing with insufficient iterations');

  // No thrashing - different files
  history = [
    createHistoryEntry(1, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(2, false, [{ ruleId: 'r1', message: 'file: /src/b.ts', severity: 'warn' }]),
    createHistoryEntry(3, false, [{ ruleId: 'r1', message: 'file: /src/c.ts', severity: 'warn' }]),
    createHistoryEntry(4, false, [{ ruleId: 'r1', message: 'file: /src/d.ts', severity: 'warn' }]),
    createHistoryEntry(5, false, [{ ruleId: 'r1', message: 'file: /src/e.ts', severity: 'warn' }])
  ];
  result = checkThrashing(history);
  assert(result.thrashing === false, 'Should not detect thrashing with different files');

  // Thrashing detected - same file 5+ times
  history = [
    createHistoryEntry(1, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(2, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(3, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(4, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(5, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }])
  ];
  result = checkThrashing(history, 5);
  assert(result.thrashing === true, 'Should detect thrashing with same file 5 times');
  assert(result.affectedFiles && result.affectedFiles.includes('/src/a.ts'), 'Should include affected file');
  assert(result.message && result.message.includes('Thrashing'), 'Should have descriptive message');

  // Custom threshold
  history = [
    createHistoryEntry(1, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(2, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(3, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }])
  ];
  result = checkThrashing(history, 3);
  assert(result.thrashing === true, 'Should detect thrashing with custom threshold');

  console.log('  ✓ All thrashing tests passed');
}

function testCircuitBreaker(): void {
  console.log('Testing checkCircuitBreaker...');

  // No history
  let result = checkCircuitBreaker([]);
  assert(result.open === false, 'Should not open with no history');
  assert(result.consecutiveFailures === 0, 'Should have 0 consecutive failures');

  // All passing
  let history = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, true),
    createHistoryEntry(3, true)
  ];
  result = checkCircuitBreaker(history);
  assert(result.open === false, 'Should not open with all passing');

  // 1 failure at end
  history = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, true),
    createHistoryEntry(3, false)
  ];
  result = checkCircuitBreaker(history, 3);
  assert(result.open === false, 'Should not open with 1 failure (threshold 3)');
  assert(result.consecutiveFailures === 1, 'Should count 1 consecutive failure');

  // 2 consecutive failures at end
  history = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, false),
    createHistoryEntry(3, false)
  ];
  result = checkCircuitBreaker(history, 3);
  assert(result.open === false, 'Should not open with 2 consecutive failures (threshold 3)');
  assert(result.consecutiveFailures === 2, 'Should count 2 consecutive failures');

  // 3 consecutive failures - circuit opens
  history = [
    createHistoryEntry(1, false),
    createHistoryEntry(2, false),
    createHistoryEntry(3, false)
  ];
  result = checkCircuitBreaker(history, 3);
  assert(result.open === true, 'Should open with 3 consecutive failures');
  assert(result.consecutiveFailures === 3, 'Should count 3 consecutive failures');
  assert(result.message && result.message.includes('Circuit breaker OPEN'), 'Should have descriptive message');

  // Failure streak broken by success
  history = [
    createHistoryEntry(1, false),
    createHistoryEntry(2, false),
    createHistoryEntry(3, true),
    createHistoryEntry(4, false)
  ];
  result = checkCircuitBreaker(history, 3);
  assert(result.open === false, 'Should not open when streak broken by success');
  assert(result.consecutiveFailures === 1, 'Should reset counter after success');

  // Custom threshold
  history = [
    createHistoryEntry(1, false),
    createHistoryEntry(2, false)
  ];
  result = checkCircuitBreaker(history, 2);
  assert(result.open === true, 'Should open with custom threshold of 2');

  console.log('  ✓ All circuit breaker tests passed');
}

function testCombinedSafetyChecks(): void {
  console.log('Testing runSafetyChecks (combined)...');

  const config: IterationConfig = {
    maxIterations: 10,
    completionPromises: ['All tests pass'],
    circuitBreakerThreshold: 3
  };

  // All checks pass
  let history: IterationHistoryEntry[] = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, true)
  ];
  let result = runSafetyChecks(3, config, history);
  assert(result.canContinue === true, 'Should allow continuation when all checks pass');
  assert(!result.blockedBy, 'Should not have blockedBy when passing');

  // Max iterations exceeded
  result = runSafetyChecks(11, config, history);
  assert(result.canContinue === false, 'Should block when max iterations exceeded');
  assert(result.blockedBy === 'max_iterations', 'Should indicate max_iterations block');
  assert(result.message && result.message.includes('exceeds maximum'), 'Should have descriptive message');

  // Circuit breaker triggered
  history = [
    createHistoryEntry(1, false),
    createHistoryEntry(2, false),
    createHistoryEntry(3, false)
  ];
  result = runSafetyChecks(4, config, history);
  assert(result.canContinue === false, 'Should block when circuit breaker opens');
  assert(result.blockedBy === 'circuit_breaker', 'Should indicate circuit_breaker block');
  assert(result.message && result.message.includes('Circuit breaker'), 'Should have descriptive message');

  // Quality regression detected
  history = [
    createHistoryEntry(1, true),
    createHistoryEntry(2, false),
    createHistoryEntry(3, false),
    createHistoryEntry(4, false)
  ];
  result = runSafetyChecks(5, config, history);
  assert(result.canContinue === false, 'Should block on quality regression');
  assert(result.blockedBy === 'quality_regression', 'Should indicate quality_regression block');

  // Thrashing detected
  history = [
    createHistoryEntry(1, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(2, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(3, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(4, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }]),
    createHistoryEntry(5, false, [{ ruleId: 'r1', message: 'file: /src/a.ts', severity: 'warn' }])
  ];
  result = runSafetyChecks(6, config, history);
  assert(result.canContinue === false, 'Should block on thrashing');
  assert(result.blockedBy === 'thrashing', 'Should indicate thrashing block');

  // Priority order: max_iterations > circuit_breaker > quality_regression > thrashing
  // Test that max_iterations takes precedence
  history = [
    createHistoryEntry(1, false),
    createHistoryEntry(2, false),
    createHistoryEntry(3, false)
  ];
  result = runSafetyChecks(11, config, history); // Exceeds max AND has circuit breaker
  assert(result.blockedBy === 'max_iterations', 'Max iterations should take precedence');

  console.log('  ✓ All combined safety checks tests passed');
}

// ============================================================================
// RUN ALL TESTS
// ============================================================================

function runAllTests(): void {
  console.log('\n=== Running Iteration Guards Test Suite ===\n');

  try {
    testMaxIterations();
    testQualityRegression();
    testThrashing();
    testCircuitBreaker();
    testCombinedSafetyChecks();

    console.log('\n✅ All tests passed!\n');
  } catch (error) {
    console.error('\n❌ Test failed:', error);
    process.exit(1);
  }
}

// Auto-run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runAllTests();
}

export { runAllTests };
