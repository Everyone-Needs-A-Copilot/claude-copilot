/**
 * Test stream path pattern matching
 *
 * Verifies:
 * 1. pathMatchesPattern: exact match, * wildcard, ** glob, directory prefix /
 * 2. Rejects patterns with >10 wildcards (throws error)
 * 3. Rejects patterns >500 chars (throws error)
 * 4. Empty pattern/path handling
 */

import { pathMatchesPattern } from '../stream.js';

function assert(condition: boolean, message: string): void {
  if (!condition) {
    throw new Error(`Assertion failed: ${message}`);
  }
}

async function runTests() {
  console.log('🧪 Testing Stream Path Pattern Matching\n');

  let testCount = 0;
  let passCount = 0;
  let failCount = 0;

  // Test 1: Exact path match
  testCount++;
  console.log(`Test ${testCount}: Exact path match`);
  try {
    assert(
      pathMatchesPattern('src/index.ts', 'src/index.ts') === true,
      'Should match exact path'
    );
    assert(
      pathMatchesPattern('src/index.ts', 'src/other.ts') === false,
      'Should not match different path'
    );
    assert(
      pathMatchesPattern('src/index.ts', 'src') === true,
      'Should match directory prefix'
    );
    assert(
      pathMatchesPattern('src/nested/file.ts', 'src') === true,
      'Should match directory prefix for nested path'
    );

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 2: * wildcard (single directory level)
  testCount++;
  console.log(`Test ${testCount}: * wildcard (single level)`);
  try {
    assert(
      pathMatchesPattern('src/index.ts', 'src/*.ts') === true,
      'Should match single level wildcard'
    );
    assert(
      pathMatchesPattern('src/nested/file.ts', 'src/*.ts') === false,
      'Should not match nested path with single level wildcard'
    );
    assert(
      pathMatchesPattern('src/index.js', 'src/*.ts') === false,
      'Should not match different extension'
    );
    assert(
      pathMatchesPattern('test/file.ts', 'src/*.ts') === false,
      'Should not match different directory'
    );

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 3: ** glob (multiple directory levels)
  testCount++;
  console.log(`Test ${testCount}: ** glob (multiple levels)`);
  try {
    assert(
      pathMatchesPattern('src/index.ts', 'src/**/*.ts') === true,
      'Should match single level with ** glob'
    );
    assert(
      pathMatchesPattern('src/nested/file.ts', 'src/**/*.ts') === true,
      'Should match nested path with ** glob'
    );
    assert(
      pathMatchesPattern('src/deeply/nested/file.ts', 'src/**/*.ts') === true,
      'Should match deeply nested path with ** glob'
    );
    assert(
      pathMatchesPattern('test/file.ts', 'src/**/*.ts') === false,
      'Should not match different directory with ** glob'
    );
    assert(
      pathMatchesPattern('src/nested/file.js', 'src/**/*.ts') === false,
      'Should not match different extension with ** glob'
    );

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 4: Directory prefix with trailing slash
  testCount++;
  console.log(`Test ${testCount}: Directory prefix with trailing slash`);
  try {
    assert(
      pathMatchesPattern('src/index.ts', 'src/') === true,
      'Should match file in directory with trailing slash'
    );
    assert(
      pathMatchesPattern('src/nested/file.ts', 'src/') === true,
      'Should match nested file in directory with trailing slash'
    );
    assert(
      pathMatchesPattern('test/file.ts', 'src/') === false,
      'Should not match file in different directory'
    );
    assert(
      pathMatchesPattern('srcOther/file.ts', 'src/') === false,
      'Should not match directory with similar prefix'
    );

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 5: Rejects patterns with >10 wildcards
  testCount++;
  console.log(`Test ${testCount}: Rejects patterns with >10 wildcards`);
  try {
    let errorThrown = false;
    try {
      pathMatchesPattern('src/file.ts', 'src/*/*/*/*/*/*/*/*/*/*/*/*.ts'); // 11 wildcards
    } catch (e) {
      errorThrown = true;
      assert(
        e instanceof Error && e.message.includes('Too many wildcards'),
        'Should throw error with "Too many wildcards" message'
      );
    }
    assert(errorThrown, 'Should throw error for >10 wildcards');

    // Boundary: exactly 10 wildcards should work
    const result = pathMatchesPattern('a/b/c/d/e/f/g/h/i/j/file.ts', 'a/*/*/*/*/*/*/*/*/*/*.ts'); // exactly 10 *
    assert(result === true, 'Should handle exactly 10 wildcards');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 6: Rejects patterns >500 chars
  testCount++;
  console.log(`Test ${testCount}: Rejects patterns >500 chars`);
  try {
    let errorThrown = false;
    const longPattern = 'a'.repeat(501);
    try {
      pathMatchesPattern('src/file.ts', longPattern);
    } catch (e) {
      errorThrown = true;
      assert(
        e instanceof Error && e.message.includes('Pattern too long'),
        'Should throw error with "Pattern too long" message'
      );
    }
    assert(errorThrown, 'Should throw error for >500 chars');

    // Boundary: 500 chars should work
    const boundaryPattern = 'a'.repeat(500);
    const result = pathMatchesPattern('a'.repeat(500), boundaryPattern);
    assert(result === true, 'Should handle exactly 500 chars');

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 7: Empty pattern/path handling
  testCount++;
  console.log(`Test ${testCount}: Empty pattern/path handling`);
  try {
    assert(
      pathMatchesPattern('src/file.ts', '') === false,
      'Should return false for empty pattern'
    );
    assert(
      pathMatchesPattern('', 'src/*.ts') === false,
      'Should return false for empty path'
    );
    assert(
      pathMatchesPattern('', '') === false,
      'Should return false for both empty'
    );

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 8: ? wildcard (single character)
  testCount++;
  console.log(`Test ${testCount}: ? wildcard (single character)`);
  try {
    assert(
      pathMatchesPattern('src/file1.ts', 'src/file?.ts') === true,
      'Should match single character with ?'
    );
    assert(
      pathMatchesPattern('src/file10.ts', 'src/file?.ts') === false,
      'Should not match multiple characters with single ?'
    );
    assert(
      pathMatchesPattern('src/file.ts', 'src/file?.ts') === false,
      'Should not match when character is missing'
    );

    console.log('  ✅ PASSED\n');
    passCount++;
  } catch (error) {
    console.log(`  ❌ FAILED: ${error instanceof Error ? error.message : String(error)}\n`);
    failCount++;
  }

  // Test 9: Complex glob patterns
  testCount++;
  console.log(`Test ${testCount}: Complex glob patterns`);
  try {
    assert(
      pathMatchesPattern('src/components/Button.tsx', 'src/**/Button.tsx') === true,
      'Should match ** with specific filename'
    );
    assert(
      pathMatchesPattern('src/components/ui/Button.tsx', 'src/**/Button.tsx') === true,
      'Should match ** with deeply nested specific filename'
    );
    assert(
      pathMatchesPattern('mcp-servers/task-copilot/src/tools/stream.ts', 'mcp-servers/**/*.ts') === true,
      'Should match real-world path pattern'
    );
    assert(
      pathMatchesPattern('mcp-servers/task-copilot/src/tools/__tests__/stream-paths.test.ts', 'mcp-servers/**/__tests__/*.ts') === true,
      'Should match test file pattern'
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
