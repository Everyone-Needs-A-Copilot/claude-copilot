/**
 * Test model router threshold parsing
 *
 * Verifies:
 * 1. parseThresholdEnv: returns null for undefined/empty
 * 2. Returns valid number for "0.3"
 * 3. Returns null for "abc"/NaN
 * 4. Returns null for 0 or 1 (boundary - must be exclusive)
 * 5. Returns valid for 0.001 and 0.999
 */

import { parseThresholdEnv } from '../model-router.js';

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

async function runTests() {
  console.log('🧪 Testing Model Router Threshold Parsing\n');

  let testCount = 0;
  let passCount = 0;
  let failCount = 0;

  // Test 1: Returns null for undefined/empty
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv returns null for undefined/empty`);
  try {
    assert(parseThresholdEnv(undefined) === null, 'Should return null for undefined');
    assert(parseThresholdEnv('') === null, 'Should return null for empty string');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 2: Returns valid number for valid input
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv returns valid number`);
  try {
    assert(parseThresholdEnv('0.3') === 0.3, 'Should return 0.3 for "0.3"');
    assert(parseThresholdEnv('0.5') === 0.5, 'Should return 0.5 for "0.5"');
    assert(parseThresholdEnv('0.7') === 0.7, 'Should return 0.7 for "0.7"');
    assert(parseThresholdEnv('0.01') === 0.01, 'Should return 0.01 for "0.01"');
    assert(parseThresholdEnv('0.99') === 0.99, 'Should return 0.99 for "0.99"');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 3: Returns null for invalid input (NaN, non-numeric)
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv returns null for NaN/non-numeric`);
  try {
    assert(parseThresholdEnv('abc') === null, 'Should return null for "abc"');
    assert(parseThresholdEnv('not a number') === null, 'Should return null for "not a number"');
    assert(parseThresholdEnv('0.3.5') === null, 'Should return null for invalid format');
    assert(parseThresholdEnv('NaN') === null, 'Should return null for "NaN"');
    assert(parseThresholdEnv('Infinity') === null, 'Should return null for "Infinity"');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 4: Returns null for boundary values 0 and 1 (exclusive range)
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv returns null for 0 and 1 (boundaries)`);
  try {
    assert(parseThresholdEnv('0') === null, 'Should return null for "0" (boundary)');
    assert(parseThresholdEnv('1') === null, 'Should return null for "1" (boundary)');
    assert(parseThresholdEnv('0.0') === null, 'Should return null for "0.0" (boundary)');
    assert(parseThresholdEnv('1.0') === null, 'Should return null for "1.0" (boundary)');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 5: Returns valid for near-boundary values (0.001 and 0.999)
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv returns valid for near-boundary`);
  try {
    assert(parseThresholdEnv('0.001') === 0.001, 'Should return 0.001 for "0.001"');
    assert(parseThresholdEnv('0.999') === 0.999, 'Should return 0.999 for "0.999"');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 6: Returns null for negative values
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv returns null for negative values`);
  try {
    assert(parseThresholdEnv('-0.5') === null, 'Should return null for "-0.5"');
    assert(parseThresholdEnv('-1') === null, 'Should return null for "-1"');
    assert(parseThresholdEnv('-0.001') === null, 'Should return null for "-0.001"');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 7: Returns null for values > 1
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv returns null for values > 1`);
  try {
    assert(parseThresholdEnv('1.5') === null, 'Should return null for "1.5"');
    assert(parseThresholdEnv('2') === null, 'Should return null for "2"');
    assert(parseThresholdEnv('100') === null, 'Should return null for "100"');
    assert(parseThresholdEnv('1.001') === null, 'Should return null for "1.001"');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 8: Edge cases with whitespace
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv handles whitespace`);
  try {
    // JavaScript Number() trims whitespace, so these should work
    assert(parseThresholdEnv(' 0.5 ') === 0.5, 'Should handle leading/trailing whitespace');
    assert(parseThresholdEnv('  0.3  ') === 0.3, 'Should handle multiple whitespace');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 9: Scientific notation (edge case)
  testCount++;
  console.log(`Test ${testCount}: parseThresholdEnv handles scientific notation`);
  try {
    // 5e-1 = 0.5, which is valid (0 < 0.5 < 1)
    assert(parseThresholdEnv('5e-1') === 0.5, 'Should parse "5e-1" as 0.5');

    // 1e0 = 1.0, which is invalid (boundary)
    assert(parseThresholdEnv('1e0') === null, 'Should return null for "1e0" (equals 1)');

    // 0e0 = 0.0, which is invalid (boundary)
    assert(parseThresholdEnv('0e0') === null, 'Should return null for "0e0" (equals 0)');

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
