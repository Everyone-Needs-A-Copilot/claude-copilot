/**
 * Tests for activation mode detection
 */

import { describe, it, expect } from '@jest/globals';
import { detectActivationMode, isValidActivationMode } from '../mode-detection.js';

describe('detectActivationMode', () => {
  describe('single keyword detection', () => {
    it('should detect ultrawork keyword', () => {
      expect(detectActivationMode('Use ultrawork for this task')).toBe('ultrawork');
      expect(detectActivationMode('ULTRAWORK mode please')).toBe('ultrawork');
      expect(detectActivationMode('ultrawork')).toBe('ultrawork');
    });

    it('should detect ultrawork from GSD keywords', () => {
      expect(detectActivationMode('Simple bug fix')).toBe('ultrawork');
      expect(detectActivationMode('Minor change needed')).toBe('ultrawork');
      expect(detectActivationMode('Fix typo in README')).toBe('ultrawork');
      expect(detectActivationMode('Hotfix for production')).toBe('ultrawork');
      expect(detectActivationMode('Tweak the styling')).toBe('ultrawork');
    });

    it('should detect analyze keyword', () => {
      expect(detectActivationMode('Please analyze this code')).toBe('analyze');
      expect(detectActivationMode('Run analysis on the data')).toBe('analyze');
      expect(detectActivationMode('Analyse the performance')).toBe('analyze');
    });

    it('should detect quick keyword', () => {
      expect(detectActivationMode('Quick fix needed')).toBe('quick');
      expect(detectActivationMode('Fast implementation')).toBe('quick');
      expect(detectActivationMode('Rapid prototyping')).toBe('quick');
    });

    it('should detect thorough keyword', () => {
      expect(detectActivationMode('Thorough review required')).toBe('thorough');
      expect(detectActivationMode('Comprehensive testing')).toBe('thorough');
      expect(detectActivationMode('Detailed analysis')).toBe('thorough');
      expect(detectActivationMode('In-depth investigation')).toBe('thorough');
    });

    it('should detect thorough from complex/architecture keywords', () => {
      expect(detectActivationMode('Complex refactoring needed')).toBe('thorough');
      expect(detectActivationMode('Architecture review')).toBe('thorough');
      expect(detectActivationMode('Refactor authentication module')).toBe('thorough');
      expect(detectActivationMode('Redesign the API')).toBe('thorough');
      expect(detectActivationMode('System-wide changes')).toBe('thorough');
    });
  });

  describe('multiple keyword detection (last wins)', () => {
    it('should return the last keyword when multiple present', () => {
      expect(detectActivationMode('Quick analyze please')).toBe('analyze');
      expect(detectActivationMode('Analyze this quickly')).toBe('quick');
      expect(detectActivationMode('Quick thorough review')).toBe('thorough');
      expect(detectActivationMode('Thorough quick fix')).toBe('quick');
    });

    it('should handle all keywords (last wins)', () => {
      expect(detectActivationMode('ultrawork analyze quick thorough')).toBe('thorough');
      expect(detectActivationMode('thorough quick analyze ultrawork')).toBe('ultrawork');
    });
  });

  describe('title and description combination', () => {
    it('should check both title and description', () => {
      expect(detectActivationMode('Fix bug', 'Use quick mode')).toBe('quick');
      expect(detectActivationMode('Use quick mode', 'But do thorough testing')).toBe('thorough');
    });

    it('should work with description only', () => {
      expect(detectActivationMode('Regular task', 'ultrawork needed')).toBe('ultrawork');
    });

    it('should work with title only when no description', () => {
      expect(detectActivationMode('Analyze this')).toBe('analyze');
      expect(detectActivationMode('Analyze this', undefined)).toBe('analyze');
    });
  });

  describe('no keyword detection', () => {
    it('should return null when no keywords found', () => {
      expect(detectActivationMode('Regular task')).toBeNull();
      expect(detectActivationMode('Implement feature')).toBeNull();
      expect(detectActivationMode('Fix the login bug')).toBeNull();
    });

    it('should not match partial words', () => {
      expect(detectActivationMode('quarterback')).toBeNull(); // contains 'quick' but not whole word
      expect(detectActivationMode('paralyzed')).toBeNull(); // contains 'analyze' but not whole word
    });
  });

  describe('case insensitivity', () => {
    it('should detect keywords regardless of case', () => {
      expect(detectActivationMode('ULTRAWORK MODE')).toBe('ultrawork');
      expect(detectActivationMode('Analyze This')).toBe('analyze');
      expect(detectActivationMode('QUICK FIX')).toBe('quick');
      expect(detectActivationMode('Thorough Review')).toBe('thorough');
    });
  });
});

describe('isValidActivationMode', () => {
  it('should validate correct modes', () => {
    expect(isValidActivationMode('ultrawork')).toBe(true);
    expect(isValidActivationMode('analyze')).toBe(true);
    expect(isValidActivationMode('quick')).toBe(true);
    expect(isValidActivationMode('thorough')).toBe(true);
  });

  it('should reject invalid modes', () => {
    expect(isValidActivationMode('invalid')).toBe(false);
    expect(isValidActivationMode('ULTRAWORK')).toBe(false); // case sensitive
    expect(isValidActivationMode('')).toBe(false);
    expect(isValidActivationMode('null')).toBe(false);
  });
});
