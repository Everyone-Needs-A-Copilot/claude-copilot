/**
 * Unit tests for ASCII progress bar utilities
 *
 * Tests the standalone utilities without database integration
 *
 * Note: This uses a simple test runner pattern matching the project style.
 * For Jest-style tests, these would need to be adapted to the test framework.
 */

import {
  renderProgressBar,
  renderMultiProgressBars,
  calculateTrendIndicator
} from '../progress-bar.js';

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

function assertContains(str: string, substring: string): void {
  assert(str.includes(substring), `Expected "${str}" to contain "${substring}"`);
}

function assertNotContains(str: string, substring: string): void {
  assert(!str.includes(substring), `Expected "${str}" to not contain "${substring}"`);
}

function assertMatches(str: string, pattern: RegExp): void {
  assert(pattern.test(str), `Expected "${str}" to match ${pattern}`);
}

async function runTest(name: string, fn: () => void): Promise<void> {
  testCount++;
  console.log(`\n${testCount}. ${name}`);

  try {
    fn();
    passCount++;
    console.log('✓ PASSED');
  } catch (error) {
    failCount++;
    console.error('✗ FAILED:', (error as Error).message);
  }
}

// ============================================================================
// RENDER PROGRESS BAR TESTS
// ============================================================================

async function testRenderProgressBarBasic(): Promise<void> {
  // 0% progress
  const bar0 = renderProgressBar(0, 10);
  assertContains(bar0, '0%');
  assertContains(bar0, '(0/10)');
  assertMatches(bar0, /\[░+\]/);

  // 50% progress
  const bar50 = renderProgressBar(5, 10);
  assertContains(bar50, '50%');
  assertContains(bar50, '(5/10)');
  assertContains(bar50, '█');
  assertContains(bar50, '░');

  // 100% progress
  const bar100 = renderProgressBar(10, 10);
  assertContains(bar100, '100%');
  assertContains(bar100, '(10/10)');
  assertMatches(bar100, /\[█+\]/);
  assertNotContains(bar100, '░');

  // Partial progress
  const bar35 = renderProgressBar(7, 20);
  assertContains(bar35, '35%');
  assertContains(bar35, '(7/20)');
}

async function testRenderProgressBarOptions(): Promise<void> {
  // Custom width
  const widthBar = renderProgressBar(5, 10, { width: 10 });
  const match = widthBar.match(/\[(.+?)\]/);
  assert(!!match, 'Should have brackets');
  assert(match![1].length === 10, 'Bar width should be 10');

  // Custom characters
  const customBar = renderProgressBar(5, 10, { filled: '#', empty: '-' });
  assertContains(customBar, '#');
  assertContains(customBar, '-');
  assertNotContains(customBar, '█');
  assertNotContains(customBar, '░');

  // Hide percentage
  const noPercent = renderProgressBar(5, 10, { showPercentage: false });
  assertNotContains(noPercent, '%');
  assertContains(noPercent, '(5/10)');

  // Hide count
  const noCount = renderProgressBar(5, 10, { showCount: false });
  assertContains(noCount, '50%');
  assertNotContains(noCount, '(5/10)');

  // Hide both
  const barOnly = renderProgressBar(5, 10, {
    showPercentage: false,
    showCount: false
  });
  assertNotContains(barOnly, '%');
  assertNotContains(barOnly, '(');
  assertMatches(barOnly, /^\[.+\]$/);
}

async function testRenderProgressBarEdgeCases(): Promise<void> {
  // Zero total
  const zeroBar = renderProgressBar(0, 0);
  assertContains(zeroBar, '0%');
  assertContains(zeroBar, '(0/0)');

  // Completed > total
  const overBar = renderProgressBar(15, 10);
  assertContains(overBar, '150%');
  assertContains(overBar, '(15/10)');

  // Very large numbers
  const largeBar = renderProgressBar(500, 1000);
  assertContains(largeBar, '50%');
  assertContains(largeBar, '(500/1000)');

  // Single item
  const single0 = renderProgressBar(0, 1);
  assertContains(single0, '0%');
  assertContains(single0, '(0/1)');

  const single1 = renderProgressBar(1, 1);
  assertContains(single1, '100%');
  assertContains(single1, '(1/1)');
}

async function testRenderProgressBarVisualAccuracy(): Promise<void> {
  // 50% of width 20 = 10 filled
  const bar50 = renderProgressBar(5, 10, { width: 20 });
  const match50 = bar50.match(/\[(.+?)\]/);
  const filledCount50 = (match50![1].match(/█/g) || []).length;
  const emptyCount50 = (match50![1].match(/░/g) || []).length;
  assert(filledCount50 === 10, 'Should have 10 filled characters');
  assert(emptyCount50 === 10, 'Should have 10 empty characters');

  // 25% of width 20 = 5 filled
  const bar25 = renderProgressBar(5, 20, { width: 20 });
  const match25 = bar25.match(/\[(.+?)\]/);
  const filledCount25 = (match25![1].match(/█/g) || []).length;
  const emptyCount25 = (match25![1].match(/░/g) || []).length;
  assert(filledCount25 === 5, 'Should have 5 filled characters');
  assert(emptyCount25 === 15, 'Should have 15 empty characters');
}

// ============================================================================
// RENDER MULTI PROGRESS BARS TESTS
// ============================================================================

async function testRenderMultiProgressBars(): Promise<void> {
  const items = [
    { label: 'Frontend', completed: 5, total: 10 },
    { label: 'Backend', completed: 8, total: 10 }
  ];

  const result = renderMultiProgressBars(items);
  const lines = result.split('\n');

  assert(lines.length === 2, 'Should have 2 lines');
  assertContains(lines[0], 'Frontend');
  assertContains(lines[0], '50%');
  assertContains(lines[1], 'Backend');
  assertContains(lines[1], '80%');

  // Test label alignment
  const label1End = lines[0].indexOf(':');
  const label2End = lines[1].indexOf(':');
  assert(label1End === label2End, 'Labels should be aligned');
}

async function testRenderMultiProgressBarsEdgeCases(): Promise<void> {
  // Empty array
  const empty = renderMultiProgressBars([]);
  assert(empty === '', 'Empty array should return empty string');

  // Single item
  const single = renderMultiProgressBars([
    { label: 'Only', completed: 5, total: 10 }
  ]);
  assertContains(single, 'Only');
  assertContains(single, '50%');
  assertNotContains(single, '\n');

  // Three items
  const three = renderMultiProgressBars([
    { label: 'A', completed: 1, total: 10 },
    { label: 'B', completed: 5, total: 10 },
    { label: 'C', completed: 9, total: 10 }
  ]);
  const threeLines = three.split('\n');
  assert(threeLines.length === 3, 'Should have 3 lines');
  assertContains(threeLines[0], '10%');
  assertContains(threeLines[1], '50%');
  assertContains(threeLines[2], '90%');
}

// ============================================================================
// CALCULATE TREND INDICATOR TESTS
// ============================================================================

async function testTrendIndicatorImproving(): Promise<void> {
  assert(calculateTrendIndicator(12, 10) === '↗', '20% improvement');
  assert(calculateTrendIndicator(15, 10) === '↗', '50% improvement');
  assert(calculateTrendIndicator(20, 10) === '↗', '100% improvement');
  assert(calculateTrendIndicator(10.21, 10, 0.02) === '↗', 'Just above threshold');
}

async function testTrendIndicatorDeclining(): Promise<void> {
  assert(calculateTrendIndicator(8, 10) === '↘', '20% decline');
  assert(calculateTrendIndicator(5, 10) === '↘', '50% decline');
  assert(calculateTrendIndicator(2, 10) === '↘', '80% decline');
  assert(calculateTrendIndicator(9.79, 10, 0.02) === '↘', 'Just above threshold');
}

async function testTrendIndicatorStable(): Promise<void> {
  assert(calculateTrendIndicator(10, 10) === '→', 'No change');
  assert(calculateTrendIndicator(10.5, 10, 0.1) === '→', 'Small increase below threshold');
  assert(calculateTrendIndicator(9.5, 10, 0.1) === '→', 'Small decrease below threshold');
  assert(calculateTrendIndicator(10.9, 10) === '→', 'Just below default threshold');
  assert(calculateTrendIndicator(9.1, 10) === '→', 'Just below default threshold (decrease)');
}

async function testTrendIndicatorEdgeCases(): Promise<void> {
  assert(calculateTrendIndicator(10, 0) === '↗', 'From 0 to positive');
  assert(calculateTrendIndicator(0, 0) === '→', 'Both zero');
  assert(calculateTrendIndicator(0, 10) === '↘', 'To zero from positive');
  assert(calculateTrendIndicator(-5, -10) === '↗', 'Negative numbers (-5 > -10)');
  assert(calculateTrendIndicator(0.12, 0.10) === '↗', 'Very small numbers');
  assert(calculateTrendIndicator(1200, 1000) === '↗', 'Very large numbers');
}

async function testTrendIndicatorCustomThresholds(): Promise<void> {
  // 5% threshold
  assert(calculateTrendIndicator(10.6, 10, 0.05) === '↗', '6% improvement with 5% threshold');
  assert(calculateTrendIndicator(10.4, 10, 0.05) === '→', '4% improvement with 5% threshold');
  assert(calculateTrendIndicator(9.4, 10, 0.05) === '↘', '6% decline with 5% threshold');

  // 20% threshold
  assert(calculateTrendIndicator(12.5, 10, 0.2) === '↗', '25% improvement with 20% threshold');
  assert(calculateTrendIndicator(11, 10, 0.2) === '→', '10% improvement with 20% threshold');
  assert(calculateTrendIndicator(7.5, 10, 0.2) === '↘', '25% decline with 20% threshold');

  // Zero threshold (any change detected)
  assert(calculateTrendIndicator(10.001, 10, 0) === '↗', 'Tiny improvement with 0 threshold');
  assert(calculateTrendIndicator(10, 10, 0) === '→', 'No change with 0 threshold');
  assert(calculateTrendIndicator(9.999, 10, 0) === '↘', 'Tiny decline with 0 threshold');
}

// ============================================================================
// RUN ALL TESTS
// ============================================================================

async function runAllTests(): Promise<void> {
  console.log('\n' + '='.repeat(60));
  console.log('PROGRESS BAR UTILITY UNIT TESTS');
  console.log('='.repeat(60));

  // renderProgressBar tests
  await runTest('renderProgressBar: basic rendering', testRenderProgressBarBasic);
  await runTest('renderProgressBar: options', testRenderProgressBarOptions);
  await runTest('renderProgressBar: edge cases', testRenderProgressBarEdgeCases);
  await runTest('renderProgressBar: visual accuracy', testRenderProgressBarVisualAccuracy);

  // renderMultiProgressBars tests
  await runTest('renderMultiProgressBars: basic', testRenderMultiProgressBars);
  await runTest('renderMultiProgressBars: edge cases', testRenderMultiProgressBarsEdgeCases);

  // calculateTrendIndicator tests
  await runTest('calculateTrendIndicator: improving', testTrendIndicatorImproving);
  await runTest('calculateTrendIndicator: declining', testTrendIndicatorDeclining);
  await runTest('calculateTrendIndicator: stable', testTrendIndicatorStable);
  await runTest('calculateTrendIndicator: edge cases', testTrendIndicatorEdgeCases);
  await runTest('calculateTrendIndicator: custom thresholds', testTrendIndicatorCustomThresholds);

  // Print summary
  console.log('\n' + '='.repeat(60));
  console.log('TEST SUMMARY');
  console.log('='.repeat(60));
  console.log(`Total: ${testCount}`);
  console.log(`✓ Passed: ${passCount}`);
  console.log(`✗ Failed: ${failCount}`);
  console.log('='.repeat(60));

  process.exit(failCount > 0 ? 1 : 0);
}

// Run tests if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runAllTests().catch(error => {
    console.error('Fatal error:', error);
    process.exit(1);
  });
}
