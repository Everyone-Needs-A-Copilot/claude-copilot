/**
 * Integration test for activation mode detection
 *
 * Tests the full flow: task creation with mode detection → retrieval with mode
 */

import Database from 'better-sqlite3';
import { DatabaseClient } from '../../database.js';
import { taskCreate, taskGet } from '../task.js';
import { initiativeLink } from '../initiative.js';
import { prdCreate } from '../prd.js';

describe('Activation Mode Integration', () => {
  let db: DatabaseClient;

  beforeEach(() => {
    // Create in-memory database for testing
    const sqliteDb = new Database(':memory:');
    db = new DatabaseClient(sqliteDb);

    // Set up test initiative and PRD
    initiativeLink(db, {
      initiativeId: 'INIT-test',
      title: 'Test Initiative',
      description: 'Test'
    });

    prdCreate(db, {
      initiativeId: 'INIT-test',
      title: 'Test PRD',
      content: 'Test content'
    });
  });

  afterEach(() => {
    db.close();
  });

  describe('Auto-detection', () => {
    it('should detect "quick" from title', async () => {
      const created = await taskCreate(db, {
        title: 'Quick bug fix',
        description: 'Fix the login issue'
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBe('quick');
    });

    it('should detect "analyze" from description', async () => {
      const created = await taskCreate(db, {
        title: 'Code review',
        description: 'Analyze the authentication flow'
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBe('analyze');
    });

    it('should detect "thorough" from title', async () => {
      const created = await taskCreate(db, {
        title: 'Comprehensive security audit',
        description: 'Check all endpoints'
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBe('thorough');
    });

    it('should detect "ultrawork" from description', async () => {
      const created = await taskCreate(db, {
        title: 'Major refactor',
        description: 'Use ultrawork mode for this task'
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBe('ultrawork');
    });

    it('should return null when no keywords found', async () => {
      const created = await taskCreate(db, {
        title: 'Implement feature',
        description: 'Add dark mode to dashboard'
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBeNull();
    });

    it('should use last keyword when multiple present', async () => {
      const created = await taskCreate(db, {
        title: 'Quick review',
        description: 'Do a thorough check of the code'
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBe('thorough');
    });
  });

  describe('Explicit override', () => {
    it('should use explicit mode over auto-detection', async () => {
      const created = await taskCreate(db, {
        title: 'Quick task',
        description: 'Fast fix needed',
        metadata: {
          activationMode: 'ultrawork'
        }
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBe('ultrawork');
    });

    it('should allow explicit null', async () => {
      const created = await taskCreate(db, {
        title: 'Analyze this code',
        description: 'Quick analysis',
        metadata: {
          activationMode: null
        }
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBeNull();
    });

    it('should throw error for invalid mode', async () => {
      await expect(
        taskCreate(db, {
          title: 'Test task',
          metadata: {
            activationMode: 'invalid' as any
          }
        })
      ).rejects.toThrow('Invalid activationMode');
    });
  });

  describe('Metadata preservation', () => {
    it('should preserve other metadata fields', async () => {
      const created = await taskCreate(db, {
        title: 'Quick task with metadata',
        metadata: {
          complexity: 'High',
          priority: 'P0',
          customField: 'value'
        }
      });

      const retrieved = taskGet(db, { id: created.id });
      expect(retrieved.metadata.activationMode).toBe('quick');
      expect(retrieved.metadata.complexity).toBe('High');
      expect(retrieved.metadata.priority).toBe('P0');
      expect(retrieved.metadata.customField).toBe('value');
    });
  });
});
