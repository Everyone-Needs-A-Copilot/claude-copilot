/**
 * Keyword Parser Tests
 *
 * Validates keyword parser meets acceptance criteria:
 * - Extracts modifier + action correctly from valid commands
 * - Rejects invalid combinations with helpful errors
 * - Case-insensitive keyword matching
 * - No false positives (economics: does NOT match eco:)
 */

import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  parseKeywords,
  formatError,
  isValidKeyword,
  getValidKeywords,
  type ParseResult,
} from './keyword-parser.js';

describe('Keyword Parser', () => {
  // ========================================================================
  // VALID COMMAND EXTRACTION
  // ========================================================================

  describe('Valid Commands', () => {
    it('should extract modifier + action correctly', () => {
      const result = parseKeywords('eco: fix the login bug');
      assert.ok(result.success);
      assert.equal(result.parsed?.modifier, 'eco');
      assert.equal(result.parsed?.action, 'fix');
      assert.equal(result.parsed?.rest, 'the login bug');
    });

    it('should extract modifier only', () => {
      const result = parseKeywords('opus: add dark mode');
      assert.ok(result.success);
      assert.equal(result.parsed?.modifier, 'opus');
      assert.equal(result.parsed?.action, 'add');
      assert.equal(result.parsed?.rest, 'dark mode');
    });

    it('should extract action only', () => {
      const result = parseKeywords('fix: broken tests');
      assert.ok(result.success);
      assert.equal(result.parsed?.modifier, undefined);
      assert.equal(result.parsed?.action, 'fix');
      assert.equal(result.parsed?.rest, 'broken tests');
    });

    it('should handle message without keywords', () => {
      const result = parseKeywords('just a regular message');
      assert.ok(result.success);
      assert.equal(result.parsed?.modifier, undefined);
      assert.equal(result.parsed?.action, undefined);
      assert.equal(result.parsed?.rest, 'just a regular message');
    });

    it('should handle empty message', () => {
      const result = parseKeywords('');
      assert.ok(result.success);
      assert.equal(result.parsed?.rest, '');
    });

    it('should handle all modifiers', () => {
      const modifiers = ['eco', 'opus', 'fast', 'slow', 'thorough', 'quick'];
      modifiers.forEach(mod => {
        const result = parseKeywords(`${mod}: test message`);
        assert.ok(result.success, `Should accept modifier "${mod}"`);
        assert.equal(result.parsed?.modifier, mod);
      });
    });

    it('should handle all actions', () => {
      const actions = ['fix', 'add', 'refactor', 'optimize', 'test', 'docs', 'security', 'design'];
      actions.forEach(action => {
        const result = parseKeywords(`${action}: test message`);
        assert.ok(result.success, `Should accept action "${action}"`);
        assert.equal(result.parsed?.action, action);
      });
    });
  });

  // ========================================================================
  // CASE INSENSITIVITY
  // ========================================================================

  describe('Case Insensitivity', () => {
    it('should handle uppercase modifiers', () => {
      const result = parseKeywords('ECO: fix bug');
      assert.ok(result.success);
      assert.equal(result.parsed?.modifier, 'eco');
    });

    it('should handle mixed case modifiers', () => {
      const result = parseKeywords('Eco: fix bug');
      assert.ok(result.success);
      assert.equal(result.parsed?.modifier, 'eco');
    });

    it('should handle uppercase actions', () => {
      const result = parseKeywords('FIX: bug');
      assert.ok(result.success);
      assert.equal(result.parsed?.action, 'fix');
    });
  });

  // ========================================================================
  // FALSE POSITIVE PREVENTION
  // ========================================================================

  describe('False Positive Prevention', () => {
    it('should NOT match "economics:" as "eco:"', () => {
      const result = parseKeywords('economics: is a study');
      // Should fail because "economics" is not a valid keyword
      assert.ok(!result.success || result.parsed?.modifier !== 'eco');
    });

    it('should NOT match "fixing:" as "fix:"', () => {
      const result = parseKeywords('fixing: something');
      // Should fail because "fixing" is not a valid keyword
      assert.ok(!result.success || result.parsed?.action !== 'fix');
    });

    it('should NOT match keywords in the middle of message', () => {
      const result = parseKeywords('I need to fix: the bug');
      assert.ok(result.success);
      // The keyword is not at the start, so it should be treated as regular text
      assert.equal(result.parsed?.rest, 'I need to fix: the bug');
    });

    it('should handle colons in the message body', () => {
      const result = parseKeywords('fix: the error message: something went wrong');
      assert.ok(result.success);
      assert.equal(result.parsed?.action, 'fix');
      assert.equal(result.parsed?.rest, 'the error message: something went wrong');
    });
  });

  // ========================================================================
  // INVALID COMBINATIONS
  // ========================================================================

  describe('Invalid Combinations', () => {
    it('should reject multiple modifiers', () => {
      const result = parseKeywords('eco: opus: fix bug');
      assert.ok(!result.success);
      assert.equal(result.error?.type, 'duplicate');
      assert.ok(result.error?.message.includes('Multiple modifiers'));
    });

    it('should reject multiple actions', () => {
      const result = parseKeywords('fix: add: something');
      assert.ok(!result.success);
      assert.equal(result.error?.type, 'duplicate');
      assert.ok(result.error?.message.includes('Multiple actions'));
    });

    it('should reject unknown keywords', () => {
      const result = parseKeywords('invalid: test');
      assert.ok(!result.success);
      assert.equal(result.error?.type, 'invalid');
      assert.ok(result.error?.message.includes('Unknown keyword'));
    });

    it('should provide helpful error messages', () => {
      const result = parseKeywords('eco: eco: fix bug');
      assert.ok(!result.success);
      if (result.error) {
        const formatted = formatError(result.error);
        assert.ok(formatted.length > 0);
        assert.ok(formatted.includes(result.error.message));
      }
    });
  });

  // ========================================================================
  // HELPER FUNCTIONS
  // ========================================================================

  describe('Helper Functions', () => {
    it('isValidKeyword should return true for valid keywords', () => {
      assert.ok(isValidKeyword('eco'));
      assert.ok(isValidKeyword('fix'));
      assert.ok(isValidKeyword('ECO')); // Case insensitive
    });

    it('isValidKeyword should return false for invalid keywords', () => {
      assert.ok(!isValidKeyword('invalid'));
      assert.ok(!isValidKeyword('economics'));
    });

    it('getValidKeywords should return all valid keywords', () => {
      const { modifiers, actions } = getValidKeywords();
      assert.ok(modifiers.includes('eco'));
      assert.ok(modifiers.includes('opus'));
      assert.ok(actions.includes('fix'));
      assert.ok(actions.includes('add'));
    });
  });

  // ========================================================================
  // EDGE CASES
  // ========================================================================

  describe('Edge Cases', () => {
    it('should handle whitespace around keywords', () => {
      const result = parseKeywords('  eco:   fix bug  ');
      assert.ok(result.success);
      assert.equal(result.parsed?.modifier, 'eco');
    });

    it('should handle keyword at end of message', () => {
      const result = parseKeywords('eco:');
      assert.ok(result.success);
      assert.equal(result.parsed?.modifier, 'eco');
      assert.equal(result.parsed?.rest, '');
    });

    it('should handle multiple spaces after keyword', () => {
      const result = parseKeywords('fix:    multiple spaces');
      assert.ok(result.success);
      assert.equal(result.parsed?.rest, 'multiple spaces');
    });
  });
});

console.log('Running Keyword Parser Tests...');
