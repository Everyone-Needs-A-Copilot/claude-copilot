/**
 * Test stream token utilities
 *
 * Verifies:
 * 1. estimateTokensFromChars: edge cases (0, negative, NaN, Infinity) and normal values
 * 2. estimateTokensFromText: empty string and normal text
 * 3. Content overflow protection (>100M chars)
 */

import { estimateTokensFromChars, estimateTokensFromText } from '../stream-tokens.js';

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

async function runTests() {
  console.log('🧪 Testing Stream Token Utilities\n');

  let testCount = 0;
  let passCount = 0;
  let failCount = 0;

  // Test 1: estimateTokensFromChars - returns 0 for edge cases
  testCount++;
  console.log(`Test ${testCount}: estimateTokensFromChars returns 0 for edge cases`);
  try {
    assert(estimateTokensFromChars(0) === 0, 'Should return 0 for 0 chars');
    assert(estimateTokensFromChars(-1) === 0, 'Should return 0 for negative chars');
    assert(estimateTokensFromChars(-100) === 0, 'Should return 0 for negative chars');
    assert(estimateTokensFromChars(NaN) === 0, 'Should return 0 for NaN');
    assert(estimateTokensFromChars(Infinity) === 0, 'Should return 0 for Infinity');
    assert(estimateTokensFromChars(-Infinity) === 0, 'Should return 0 for -Infinity');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 2: estimateTokensFromChars - correct calculation for normal values
  testCount++;
  console.log(`Test ${testCount}: estimateTokensFromChars correct calculation`);
  try {
    // 4 chars = 1 token (rounded up)
    assert(estimateTokensFromChars(1) === 1, 'Should return 1 token for 1 char');
    assert(estimateTokensFromChars(4) === 1, 'Should return 1 token for 4 chars');
    assert(estimateTokensFromChars(5) === 2, 'Should return 2 tokens for 5 chars (ceil)');
    assert(estimateTokensFromChars(100) === 25, 'Should return 25 tokens for 100 chars');
    assert(estimateTokensFromChars(1000) === 250, 'Should return 250 tokens for 1000 chars');
    assert(estimateTokensFromChars(1001) === 251, 'Should return 251 tokens for 1001 chars (ceil)');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 3: estimateTokensFromChars - throws for content >100M chars
  testCount++;
  console.log(`Test ${testCount}: estimateTokensFromChars throws for content >100M chars`);
  try {
    let errorThrown = false;
    try {
      estimateTokensFromChars(100_000_001);
    } catch (e) {
      errorThrown = true;
      assert(
        e instanceof Error && e.message.includes('Content too large'),
        'Should throw error with "Content too large" message'
      );
    }
    assert(errorThrown, 'Should throw error for >100M chars');

    // Boundary: 100M should work
    const result = estimateTokensFromChars(100_000_000);
    assert(result === 25_000_000, 'Should handle exactly 100M chars');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 4: estimateTokensFromText - returns 0 for empty string
  testCount++;
  console.log(`Test ${testCount}: estimateTokensFromText returns 0 for empty string`);
  try {
    assert(estimateTokensFromText('') === 0, 'Should return 0 for empty string');
    assert(estimateTokensFromText('   ') === 0, 'Should return 0 for whitespace-only string');
    assert(estimateTokensFromText('\n\t  \n') === 0, 'Should return 0 for whitespace with newlines');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 5: estimateTokensFromText - correct estimates for normal text
  testCount++;
  console.log(`Test ${testCount}: estimateTokensFromText correct estimates`);
  try {
    const shortText = 'Hello';
    assert(estimateTokensFromText(shortText) === 2, 'Should return 2 tokens for "Hello"');

    const mediumText = 'This is a test sentence with multiple words.';
    const expectedMedium = Math.ceil(mediumText.length / 4);
    assert(
      estimateTokensFromText(mediumText) === expectedMedium,
      `Should return ${expectedMedium} tokens for medium text`
    );

    const longText = 'a'.repeat(1000);
    assert(estimateTokensFromText(longText) === 250, 'Should return 250 tokens for 1000 chars');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 6: estimateTokensFromText - handles special characters
  testCount++;
  console.log(`Test ${testCount}: estimateTokensFromText handles special characters`);
  try {
    const emojiText = '👍👎🎉';
    const expectedEmoji = Math.ceil(emojiText.length / 4);
    assert(
      estimateTokensFromText(emojiText) === expectedEmoji,
      `Should handle emoji characters`
    );

    const unicodeText = 'こんにちは世界';
    const expectedUnicode = Math.ceil(unicodeText.length / 4);
    assert(
      estimateTokensFromText(unicodeText) === expectedUnicode,
      `Should handle unicode characters`
    );

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
