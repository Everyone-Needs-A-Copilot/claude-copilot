/**
 * Tests for Stop Hook System (Phase 2)
 */

import assert from 'assert';
import {
  registerStopHook,
  unregisterStopHook,
  getStopHook,
  getTaskHooks,
  clearTaskHooks,
  clearAllHooks,
  createDefaultHook,
  createValidationHook,
  createPromiseHook,
  type AgentContext,
  type StopHookResult
} from './stop-hooks.js';

describe('Stop Hook System', () => {
  beforeEach(() => {
    // Clear all hooks before each test
    clearAllHooks();
  });

  describe('Hook Registration', () => {
    it('should register a hook', () => {
      const hookId = registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Test hook'
        })
      );

      expect(hookId).toBeDefined();
      expect(hookId).toMatch(/^HOOK-/);
    });

    it('should register a hook with custom ID', () => {
      const customId = 'my-custom-hook';
      const hookId = registerStopHook(
        { taskId: 'TASK-1', hookId: customId },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Test hook'
        })
      );

      expect(hookId).toBe(customId);
    });

    it('should register a hook with metadata', () => {
      const metadata = { description: 'Test metadata' };
      const hookId = registerStopHook(
        { taskId: 'TASK-1', metadata },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Test hook'
        })
      );

      const hook = getStopHook(hookId);
      expect(hook?.metadata).toEqual(metadata);
    });

    it('should register hook as enabled by default', () => {
      const hookId = registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Test hook'
        })
      );

      const hook = getStopHook(hookId);
      expect(hook?.enabled).toBe(true);
    });

    it('should register hook as disabled when specified', () => {
      const hookId = registerStopHook(
        { taskId: 'TASK-1', enabled: false },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Test hook'
        })
      );

      const hook = getStopHook(hookId);
      expect(hook?.enabled).toBe(false);
    });
  });

  describe('Hook Retrieval', () => {
    it('should get a registered hook by ID', () => {
      const hookId = registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Test hook'
        })
      );

      const hook = getStopHook(hookId);
      expect(hook).toBeDefined();
      expect(hook?.id).toBe(hookId);
      expect(hook?.taskId).toBe('TASK-1');
    });

    it('should return undefined for non-existent hook', () => {
      const hook = getStopHook('non-existent');
      expect(hook).toBeUndefined();
    });

    it('should get all hooks for a task', () => {
      registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Hook 1'
        })
      );

      registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Hook 2'
        })
      );

      registerStopHook(
        { taskId: 'TASK-2' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Hook 3'
        })
      );

      const task1Hooks = getTaskHooks('TASK-1');
      expect(task1Hooks).toHaveLength(2);
      expect(task1Hooks.every(h => h.taskId === 'TASK-1')).toBe(true);
    });

    it('should return empty array for task with no hooks', () => {
      const hooks = getTaskHooks('TASK-NO-HOOKS');
      expect(hooks).toEqual([]);
    });
  });

  describe('Hook Unregistration', () => {
    it('should unregister a hook by ID', () => {
      const hookId = registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Test hook'
        })
      );

      const removed = unregisterStopHook(hookId);
      expect(removed).toBe(true);

      const hook = getStopHook(hookId);
      expect(hook).toBeUndefined();
    });

    it('should return false when unregistering non-existent hook', () => {
      const removed = unregisterStopHook('non-existent');
      expect(removed).toBe(false);
    });

    it('should clear all hooks for a task', () => {
      registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Hook 1'
        })
      );

      registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Hook 2'
        })
      );

      const cleared = clearTaskHooks('TASK-1');
      expect(cleared).toBe(2);

      const hooks = getTaskHooks('TASK-1');
      expect(hooks).toEqual([]);
    });

    it('should clear all hooks', () => {
      registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Hook 1'
        })
      );

      registerStopHook(
        { taskId: 'TASK-2' },
        (context: AgentContext): StopHookResult => ({
          action: 'complete',
          reason: 'Hook 2'
        })
      );

      const cleared = clearAllHooks();
      expect(cleared).toBe(2);

      expect(getTaskHooks('TASK-1')).toEqual([]);
      expect(getTaskHooks('TASK-2')).toEqual([]);
    });
  });

  describe('Preset Hook Factories', () => {
    describe('createValidationHook', () => {
      it('should complete when all validation rules pass', async () => {
        const hookId = createValidationHook('TASK-1');
        const hook = getStopHook(hookId);
        expect(hook).toBeDefined();

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'testing',
          filesModified: [],
          validationResults: [
            { ruleName: 'tests_pass', passed: true, message: 'All tests pass' },
            { ruleName: 'lint_clean', passed: true, message: 'No lint errors' }
          ],
          completionPromises: []
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('complete');
        expect(result.reason).toContain('validation rules passed');
      });

      it('should continue when validation rules fail', async () => {
        const hookId = createValidationHook('TASK-1');
        const hook = getStopHook(hookId);

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'testing',
          filesModified: [],
          validationResults: [
            { ruleName: 'tests_pass', passed: false, message: '2 tests failed' },
            { ruleName: 'lint_clean', passed: true, message: 'No lint errors' }
          ],
          completionPromises: []
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('continue');
        expect(result.reason).toContain('failed');
        expect(result.nextPrompt).toBeDefined();
      });
    });

    describe('createPromiseHook', () => {
      it('should complete when COMPLETE promise detected', async () => {
        const hookId = createPromiseHook('TASK-1');
        const hook = getStopHook(hookId);

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'implementation',
          filesModified: [],
          validationResults: [],
          completionPromises: [
            {
              type: 'COMPLETE',
              detected: true,
              content: '<promise>COMPLETE</promise>',
              detectedAt: new Date().toISOString()
            }
          ]
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('complete');
        expect(result.reason).toContain('COMPLETE');
      });

      it('should escalate when ESCALATE promise detected', async () => {
        const hookId = createPromiseHook('TASK-1');
        const hook = getStopHook(hookId);

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'implementation',
          filesModified: [],
          validationResults: [],
          completionPromises: [
            {
              type: 'ESCALATE',
              detected: true,
              content: '<promise>ESCALATE</promise>',
              detectedAt: new Date().toISOString()
            }
          ]
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('escalate');
        expect(result.reason).toContain('ESCALATE');
      });

      it('should escalate when BLOCKED promise detected', async () => {
        const hookId = createPromiseHook('TASK-1');
        const hook = getStopHook(hookId);

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'implementation',
          filesModified: [],
          validationResults: [],
          completionPromises: [
            {
              type: 'BLOCKED',
              detected: true,
              content: '<promise>BLOCKED</promise>',
              detectedAt: new Date().toISOString()
            }
          ]
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('escalate');
        expect(result.reason).toContain('BLOCKED');
      });

      it('should continue when no promise detected', async () => {
        const hookId = createPromiseHook('TASK-1');
        const hook = getStopHook(hookId);

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'implementation',
          filesModified: [],
          validationResults: [],
          completionPromises: []
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('continue');
      });
    });

    describe('createDefaultHook', () => {
      it('should prioritize COMPLETE promise over validation', async () => {
        const hookId = createDefaultHook('TASK-1');
        const hook = getStopHook(hookId);

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'implementation',
          filesModified: [],
          validationResults: [
            { ruleName: 'tests_pass', passed: false, message: 'Tests failed' }
          ],
          completionPromises: [
            {
              type: 'COMPLETE',
              detected: true,
              content: '<promise>COMPLETE</promise>',
              detectedAt: new Date().toISOString()
            }
          ]
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('complete');
        expect(result.reason).toContain('COMPLETE');
      });

      it('should fall back to validation when no promises', async () => {
        const hookId = createDefaultHook('TASK-1');
        const hook = getStopHook(hookId);

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'implementation',
          filesModified: [],
          validationResults: [
            { ruleName: 'tests_pass', passed: true, message: 'Tests pass' }
          ],
          completionPromises: []
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('complete');
        expect(result.reason).toContain('validation rules passed');
      });

      it('should continue by default when no promises or validation', async () => {
        const hookId = createDefaultHook('TASK-1');
        const hook = getStopHook(hookId);

        const context: AgentContext = {
          taskId: 'TASK-1',
          iteration: 1,
          executionPhase: 'implementation',
          filesModified: [],
          validationResults: [],
          completionPromises: []
        };

        const result = await hook!.onComplete(context);
        expect(result.action).toBe('continue');
      });
    });
  });

  describe('Hook Callback Execution', () => {
    it('should execute hook callback with agent context', async () => {
      let callbackContext: AgentContext | null = null;

      const hookId = registerStopHook(
        { taskId: 'TASK-1' },
        (context: AgentContext): StopHookResult => {
          callbackContext = context;
          return {
            action: 'complete',
            reason: 'Test'
          };
        }
      );

      const hook = getStopHook(hookId);
      const context: AgentContext = {
        taskId: 'TASK-1',
        iteration: 5,
        executionPhase: 'testing',
        filesModified: ['file1.ts', 'file2.ts'],
        validationResults: [],
        completionPromises: []
      };

      await hook!.onComplete(context);

      expect(callbackContext).toEqual(context);
    });

    it('should support async hook callbacks', async () => {
      const hookId = registerStopHook(
        { taskId: 'TASK-1' },
        async (context: AgentContext): Promise<StopHookResult> => {
          // Simulate async operation
          await new Promise(resolve => setTimeout(resolve, 10));
          return {
            action: 'complete',
            reason: 'Async test'
          };
        }
      );

      const hook = getStopHook(hookId);
      const context: AgentContext = {
        taskId: 'TASK-1',
        iteration: 1,
        executionPhase: 'testing',
        filesModified: [],
        validationResults: [],
        completionPromises: []
      };

      const result = await hook!.onComplete(context);
      expect(result.action).toBe('complete');
      expect(result.reason).toBe('Async test');
    });
  });
});
