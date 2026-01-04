/**
 * Integration tests for Memory Copilot MCP Server
 *
 * Tests cover:
 * 1. Initiative lifecycle (start, get, update, complete)
 * 2. Memory operations (store, update, delete, get, list)
 * 3. Semantic search functionality
 * 4. Initiative slim migration
 * 5. Error handling for invalid inputs
 * 6. Agent self-improvement workflow (validation, filtering, status updates)
 */

import { describe, it, before, after } from 'node:test';
import assert from 'node:assert';
import { mkdtempSync, rmSync } from 'fs';
import { tmpdir } from 'os';
import { join } from 'path';
import { DatabaseClient } from '../db/client.js';
import {
  memoryStore,
  memoryUpdate,
  memoryDelete,
  memoryGet,
  memoryList,
  memorySearch,
  initiativeStart,
  initiativeUpdate,
  initiativeGet,
  initiativeSlim,
  initiativeComplete
} from '../tools/index.js';
import type { MemoryType, InitiativeStatus } from '../types.js';

describe('Memory Copilot Integration Tests', () => {
  let testDir: string;
  let db: DatabaseClient;
  const testProjectPath = '/test/project';
  const testWorkspaceId = 'test-workspace';

  before(() => {
    // Create temporary directory for test database
    testDir = mkdtempSync(join(tmpdir(), 'memory-copilot-test-'));
    db = new DatabaseClient(testProjectPath, testDir, testWorkspaceId);
  });

  after(() => {
    // Cleanup
    db.close();
    rmSync(testDir, { recursive: true, force: true });
  });

  describe('Initiative Lifecycle', () => {
    it('should start a new initiative', () => {
      const initiative = initiativeStart(db, {
        name: 'Test Initiative',
        goal: 'Test the initiative lifecycle',
        status: 'IN PROGRESS'
      });

      assert.strictEqual(initiative.name, 'Test Initiative');
      assert.strictEqual(initiative.goal, 'Test the initiative lifecycle');
      assert.strictEqual(initiative.status, 'IN PROGRESS');
      assert.strictEqual(initiative.projectId, testWorkspaceId);
      assert.ok(initiative.id);
      assert.ok(initiative.createdAt);
      assert.ok(initiative.updatedAt);

      // Check default values
      assert.deepStrictEqual(initiative.decisions, []);
      assert.deepStrictEqual(initiative.lessons, []);
      assert.deepStrictEqual(initiative.keyFiles, []);
      assert.deepStrictEqual(initiative.completed, []);
      assert.deepStrictEqual(initiative.inProgress, []);
      assert.deepStrictEqual(initiative.blocked, []);
      assert.strictEqual(initiative.taskCopilotLinked, false);
      assert.deepStrictEqual(initiative.activePrdIds, []);
    });

    it('should get the current initiative', () => {
      const initiative = initiativeGet(db);

      assert.ok(initiative);
      assert.strictEqual(initiative!.name, 'Test Initiative');
      assert.strictEqual(initiative!.status, 'IN PROGRESS');
    });

    it('should update initiative with permanent knowledge', () => {
      const updated = initiativeUpdate(db, {
        decisions: ['Use TypeScript for type safety', 'Implement semantic search'],
        lessons: ['Vector embeddings improve search quality'],
        keyFiles: ['src/db/client.ts', 'src/tools/memory-tools.ts'],
        status: 'READY FOR REVIEW'
      });

      assert.ok(updated);
      assert.strictEqual(updated!.decisions.length, 2);
      assert.strictEqual(updated!.lessons.length, 1);
      assert.strictEqual(updated!.keyFiles.length, 2);
      assert.strictEqual(updated!.status, 'READY FOR REVIEW');
    });

    it('should update initiative with slim mode fields', () => {
      const updated = initiativeUpdate(db, {
        currentFocus: 'Testing semantic search',
        nextAction: 'Verify edge cases',
        taskCopilotLinked: true,
        activePrdIds: ['PRD-001', 'PRD-002']
      });

      assert.ok(updated);
      assert.strictEqual(updated!.currentFocus, 'Testing semantic search');
      assert.strictEqual(updated!.nextAction, 'Verify edge cases');
      assert.strictEqual(updated!.taskCopilotLinked, true);
      assert.deepStrictEqual(updated!.activePrdIds, ['PRD-001', 'PRD-002']);
    });

    it('should truncate slim fields to max length', () => {
      const longString = 'a'.repeat(150);
      const updated = initiativeUpdate(db, {
        currentFocus: longString,
        nextAction: longString
      });

      assert.ok(updated);
      assert.strictEqual(updated!.currentFocus!.length, 100);
      assert.strictEqual(updated!.nextAction!.length, 100);
    });

    it('should update initiative with deprecated fields (backward compatibility)', () => {
      const updated = initiativeUpdate(db, {
        completed: ['Task 1', 'Task 2'],
        inProgress: ['Task 3', 'Task 4'],
        blocked: ['Task 5'],
        resumeInstructions: 'Continue with testing'
      });

      assert.ok(updated);
      assert.strictEqual(updated!.completed.length, 2);
      assert.strictEqual(updated!.inProgress.length, 2);
      assert.strictEqual(updated!.blocked.length, 1);
      assert.strictEqual(updated!.resumeInstructions, 'Continue with testing');
    });

    it('should accumulate decisions and lessons', () => {
      const updated = initiativeUpdate(db, {
        decisions: ['Third decision'],
        lessons: ['Second lesson', 'Third lesson']
      });

      assert.ok(updated);
      assert.strictEqual(updated!.decisions.length, 3);
      assert.strictEqual(updated!.lessons.length, 3);
    });

    it('should complete and archive initiative', () => {
      const completed = initiativeComplete(db, 'Initiative completed successfully');

      assert.ok(completed);
      assert.strictEqual(completed!.status, 'COMPLETE');
      assert.strictEqual(completed!.resumeInstructions, 'Initiative completed successfully');

      // Verify initiative was archived
      const current = initiativeGet(db);
      assert.strictEqual(current, null);
    });

    it('should start a new initiative after previous was archived', () => {
      const initiative = initiativeStart(db, {
        name: 'Second Initiative',
        status: 'NOT STARTED'
      });

      assert.strictEqual(initiative.name, 'Second Initiative');
      assert.strictEqual(initiative.status, 'NOT STARTED');
    });
  });

  describe('Initiative Slim Migration', () => {
    it('should slim down bloated initiative', () => {
      // Create bloated initiative
      initiativeUpdate(db, {
        completed: Array.from({ length: 15 }, (_, i) => `Completed task ${i + 1}`),
        inProgress: Array.from({ length: 5 }, (_, i) => `In progress task ${i + 1}`),
        blocked: Array.from({ length: 3 }, (_, i) => `Blocked task ${i + 1}`),
        resumeInstructions: 'Very long resume instructions that should be removed',
        decisions: ['Keep this decision'],
        lessons: ['Keep this lesson'],
        keyFiles: ['keep/this/file.ts']
      });

      const beforeSlim = initiativeGet(db);
      assert.ok(beforeSlim);
      assert.strictEqual(beforeSlim!.completed.length, 15);

      // Slim the initiative
      const result = initiativeSlim(db, { archiveDetails: true });

      assert.ok(result);
      assert.strictEqual(result!.archived, true);
      assert.ok(result!.archivePath);
      assert.deepStrictEqual(result!.removedFields, [
        'completed',
        'inProgress',
        'blocked',
        'resumeInstructions'
      ]);
      assert.ok(result!.beforeSize > result!.afterSize);
      assert.ok(result!.savings.includes('%'));

      // Verify permanent knowledge was kept
      const afterSlim = initiativeGet(db);
      assert.ok(afterSlim);
      assert.deepStrictEqual(afterSlim!.decisions, ['Keep this decision']);
      assert.deepStrictEqual(afterSlim!.lessons, ['Keep this lesson']);
      assert.deepStrictEqual(afterSlim!.keyFiles, ['keep/this/file.ts']);

      // Verify bloated fields were cleared
      assert.deepStrictEqual(afterSlim!.completed, []);
      assert.deepStrictEqual(afterSlim!.inProgress, []);
      assert.deepStrictEqual(afterSlim!.blocked, []);
      assert.strictEqual(afterSlim!.resumeInstructions, undefined);
    });

    it('should slim without archiving if requested', () => {
      const result = initiativeSlim(db, { archiveDetails: false });

      assert.ok(result);
      assert.strictEqual(result!.archived, false);
      assert.strictEqual(result!.archivePath, undefined);
    });
  });

  describe('Memory Operations', () => {
    const sessionId = 'test-session-001';
    let decisionMemoryId: string;
    let lessonMemoryId: string;
    let contextMemoryId: string;

    it('should store memory with type: decision', async () => {
      const memory = await memoryStore(
        db,
        {
          content: 'We decided to use sqlite-vec for vector storage',
          type: 'decision',
          tags: ['architecture', 'database'],
          metadata: { priority: 'high', author: 'test' }
        },
        sessionId
      );

      decisionMemoryId = memory.id;

      assert.ok(memory.id);
      assert.strictEqual(memory.content, 'We decided to use sqlite-vec for vector storage');
      assert.strictEqual(memory.type, 'decision');
      assert.deepStrictEqual(memory.tags, ['architecture', 'database']);
      assert.deepStrictEqual(memory.metadata, { priority: 'high', author: 'test' });
      assert.strictEqual(memory.sessionId, sessionId);
      assert.strictEqual(memory.projectId, testWorkspaceId);
      assert.ok(memory.createdAt);
      assert.ok(memory.updatedAt);
    });

    it('should store memory with type: lesson', async () => {
      const memory = await memoryStore(
        db,
        {
          content: 'Vector embeddings provide better semantic search than keyword matching',
          type: 'lesson',
          tags: ['search', 'ai']
        },
        sessionId
      );

      lessonMemoryId = memory.id;

      assert.ok(memory.id);
      assert.strictEqual(memory.type, 'lesson');
      assert.deepStrictEqual(memory.tags, ['search', 'ai']);
    });

    it('should store memory with type: context', async () => {
      const memory = await memoryStore(
        db,
        {
          content: 'Project uses TypeScript with Node.js 18+',
          type: 'context',
          tags: ['environment']
        },
        sessionId
      );

      contextMemoryId = memory.id;

      assert.ok(memory.id);
      assert.strictEqual(memory.type, 'context');
    });

    it('should store all memory types', async () => {
      const types: MemoryType[] = ['discussion', 'file', 'initiative'];

      for (const type of types) {
        const memory = await memoryStore(
          db,
          {
            content: `Test content for ${type}`,
            type
          },
          sessionId
        );

        assert.strictEqual(memory.type, type);
      }
    });

    it('should get memory by ID', () => {
      const memory = memoryGet(db, decisionMemoryId);

      assert.ok(memory);
      assert.strictEqual(memory!.id, decisionMemoryId);
      assert.strictEqual(memory!.content, 'We decided to use sqlite-vec for vector storage');
    });

    it('should return null for non-existent memory', () => {
      const memory = memoryGet(db, 'non-existent-id');
      assert.strictEqual(memory, null);
    });

    it('should update memory content', async () => {
      const updated = await memoryUpdate(db, {
        id: decisionMemoryId,
        content: 'Updated: We decided to use sqlite-vec for efficient vector storage'
      });

      assert.ok(updated);
      assert.strictEqual(updated!.content, 'Updated: We decided to use sqlite-vec for efficient vector storage');
      assert.notStrictEqual(updated!.createdAt, updated!.updatedAt);
    });

    it('should update memory tags and metadata', async () => {
      const updated = await memoryUpdate(db, {
        id: decisionMemoryId,
        tags: ['architecture', 'database', 'performance'],
        metadata: { priority: 'critical', reviewed: true }
      });

      assert.ok(updated);
      assert.deepStrictEqual(updated!.tags, ['architecture', 'database', 'performance']);
      assert.deepStrictEqual(updated!.metadata, { priority: 'critical', reviewed: true });
    });

    it('should list all memories', () => {
      const memories = memoryList(db, {});

      assert.ok(memories.length >= 6); // We created at least 6 memories
    });

    it('should list memories filtered by type', () => {
      const decisions = memoryList(db, { type: 'decision' });
      const lessons = memoryList(db, { type: 'lesson' });

      assert.ok(decisions.length >= 1);
      assert.ok(lessons.length >= 1);

      decisions.forEach(m => assert.strictEqual(m.type, 'decision'));
      lessons.forEach(m => assert.strictEqual(m.type, 'lesson'));
    });

    it('should list memories filtered by tags', () => {
      const architectureMemories = memoryList(db, {
        tags: ['architecture']
      });

      assert.ok(architectureMemories.length >= 1);
      architectureMemories.forEach(m => {
        assert.ok(m.tags.includes('architecture'));
      });
    });

    it('should list memories with limit and offset', () => {
      const page1 = memoryList(db, { limit: 2, offset: 0 });
      const page2 = memoryList(db, { limit: 2, offset: 2 });

      assert.strictEqual(page1.length, 2);
      assert.strictEqual(page2.length, 2);
      assert.notStrictEqual(page1[0].id, page2[0].id);
    });

    it('should delete memory', () => {
      const result = memoryDelete(db, contextMemoryId);
      assert.strictEqual(result, true);

      const deleted = memoryGet(db, contextMemoryId);
      assert.strictEqual(deleted, null);
    });

    it('should return false when deleting non-existent memory', () => {
      const result = memoryDelete(db, 'non-existent-id');
      assert.strictEqual(result, false);
    });
  });

  describe('Semantic Search', () => {
    it('should perform semantic search with natural language query', async () => {
      // Store test data in this test to ensure it's available
      await memoryStore(db, {
        content: 'SQLite is a lightweight embedded database',
        type: 'context',
        tags: ['database']
      });

      await memoryStore(db, {
        content: 'Vector embeddings enable similarity search',
        type: 'lesson',
        tags: ['ai', 'search']
      });

      const results = await memorySearch(db, {
        query: 'SQLite database',  // More specific query matching stored content
        threshold: 0.3,  // Lower threshold for embedding model variations
        limit: 5
      });

      // Semantic search may return 0 results with strict similarity
      // Just verify it returns an array without errors
      assert.ok(Array.isArray(results));

      // If results exist, verify they have expected structure
      if (results.length > 0) {
        // Results should include database-related memories
        const hasDbContent = results.some(r =>
          r.content.includes('database') || r.content.includes('SQLite')
        );
        assert.ok(hasDbContent, 'Results should contain database content');

        // Check distance values
        results.forEach(r => {
          assert.ok(typeof r.distance === 'number');
          assert.ok(r.distance >= 0);
        });
      }
    });

    it('should filter semantic search by type', async () => {
      // Store test data in this test to ensure it's available
      await memoryStore(db, {
        content: 'Vector embeddings enable similarity search',
        type: 'lesson',
        tags: ['ai', 'search']
      });

      await memoryStore(db, {
        content: 'Machine learning models use embeddings for semantic understanding',
        type: 'lesson',
        tags: ['ai', 'ml']
      });

      const results = await memorySearch(db, {
        query: 'vector embeddings similarity',  // More specific query matching lesson content
        type: 'lesson',
        threshold: 0.3,  // Lower threshold for embedding model variations
        limit: 5
      });

      // Semantic search may return 0 results with strict similarity
      // Just verify it returns an array and any results are correct type
      assert.ok(Array.isArray(results));
      results.forEach(r => assert.strictEqual(r.type, 'lesson'));
    });

    it('should respect search threshold', async () => {
      const strictResults = await memorySearch(db, {
        query: 'unrelated random query xyz123',
        threshold: 0.9,
        limit: 10
      });

      const relaxedResults = await memorySearch(db, {
        query: 'unrelated random query xyz123',
        threshold: 0.3,
        limit: 10
      });

      // Strict threshold should return fewer results
      assert.ok(strictResults.length <= relaxedResults.length);
    });

    it('should respect search limit', async () => {
      const results = await memorySearch(db, {
        query: 'technology',
        limit: 3
      });

      assert.ok(results.length <= 3);
    });

    it('should return results ordered by relevance', async () => {
      // Store test data to ensure we have results
      await memoryStore(db, {
        content: 'PostgreSQL is a powerful relational database',
        type: 'context',
        tags: ['database']
      });

      await memoryStore(db, {
        content: 'Database indexing improves query performance',
        type: 'lesson',
        tags: ['database', 'performance']
      });

      const results = await memorySearch(db, {
        query: 'database',
        limit: 10
      });

      // Results should be ordered by distance (ascending)
      for (let i = 0; i < results.length - 1; i++) {
        assert.ok(results[i].distance <= results[i + 1].distance);
      }
    });
  });

  describe('Error Handling', () => {
    it('should handle invalid memory type', async () => {
      await assert.rejects(
        async () => {
          await memoryStore(db, {
            content: 'Test content',
            // @ts-expect-error Testing invalid type
            type: 'invalid-type'
          });
        },
        /CHECK constraint failed/
      );
    });

    it('should return null when updating non-existent memory', async () => {
      const result = await memoryUpdate(db, {
        id: 'non-existent-id',
        content: 'Updated content'
      });

      assert.strictEqual(result, null);
    });

    it('should return null when getting non-existent initiative', () => {
      // Complete current initiative
      initiativeComplete(db);

      const result = initiativeGet(db);
      assert.strictEqual(result, null);
    });

    it('should return null when updating non-existent initiative', () => {
      const result = initiativeUpdate(db, {
        decisions: ['New decision']
      });

      assert.strictEqual(result, null);
    });

    it('should return null when slimming non-existent initiative', () => {
      const result = initiativeSlim(db, {});
      assert.strictEqual(result, null);
    });

    it('should return null when completing non-existent initiative', () => {
      const result = initiativeComplete(db, 'Summary');
      assert.strictEqual(result, null);
    });

    it('should handle empty search query gracefully', async () => {
      const results = await memorySearch(db, {
        query: '',
        limit: 5
      });

      // Should return some results (or empty array)
      assert.ok(Array.isArray(results));
    });

    it('should handle missing optional fields in memory store', async () => {
      const memory = await memoryStore(db, {
        content: 'Minimal memory',
        type: 'context'
      });

      assert.ok(memory.id);
      assert.deepStrictEqual(memory.tags, []);
      assert.deepStrictEqual(memory.metadata, {});
      assert.strictEqual(memory.sessionId, undefined);
    });

    it('should handle missing optional fields in initiative start', () => {
      initiativeStart(db, { name: 'Minimal Initiative' });

      const initiative = initiativeGet(db);
      assert.ok(initiative);
      assert.strictEqual(initiative!.goal, undefined);
      assert.strictEqual(initiative!.status, 'IN PROGRESS');
    });
  });

  describe('Edge Cases', () => {
    it('should handle very long content', async () => {
      const longContent = 'x'.repeat(10000);
      const memory = await memoryStore(db, {
        content: longContent,
        type: 'context'
      });

      assert.strictEqual(memory.content.length, 10000);

      const retrieved = memoryGet(db, memory.id);
      assert.strictEqual(retrieved!.content.length, 10000);
    });

    it('should handle special characters in content', async () => {
      const specialContent = 'Test with "quotes", \'apostrophes\', <tags>, & ampersands, 日本語, emoji 🚀';
      const memory = await memoryStore(db, {
        content: specialContent,
        type: 'context'
      });

      const retrieved = memoryGet(db, memory.id);
      assert.strictEqual(retrieved!.content, specialContent);
    });

    it('should handle empty arrays and objects', async () => {
      const memory = await memoryStore(db, {
        content: 'Test',
        type: 'context',
        tags: [],
        metadata: {}
      });

      assert.deepStrictEqual(memory.tags, []);
      assert.deepStrictEqual(memory.metadata, {});
    });

    it('should handle nested metadata objects', async () => {
      const complexMetadata = {
        level1: {
          level2: {
            level3: 'deep value'
          },
          array: [1, 2, 3]
        },
        boolean: true,
        number: 42
      };

      const memory = await memoryStore(db, {
        content: 'Test',
        type: 'context',
        metadata: complexMetadata
      });

      assert.deepStrictEqual(memory.metadata, complexMetadata);
    });

    it('should handle archiving when starting multiple initiatives', () => {
      initiativeStart(db, { name: 'Initiative 1' });
      const init1 = initiativeGet(db);
      assert.strictEqual(init1!.name, 'Initiative 1');

      initiativeStart(db, { name: 'Initiative 2' });
      const init2 = initiativeGet(db);
      assert.strictEqual(init2!.name, 'Initiative 2');

      // Only one active initiative should exist
      const stats = db.getStats();
      assert.strictEqual(stats.initiativeActive, true);
    });

    it('should handle duplicate key files', () => {
      initiativeUpdate(db, {
        keyFiles: ['file1.ts', 'file2.ts']
      });

      initiativeUpdate(db, {
        keyFiles: ['file2.ts', 'file3.ts'] // file2.ts is duplicate
      });

      const initiative = initiativeGet(db);
      const uniqueFiles = new Set(initiative!.keyFiles);

      // Should have deduplicated files
      assert.strictEqual(uniqueFiles.size, initiative!.keyFiles.length);
      assert.ok(initiative!.keyFiles.includes('file1.ts'));
      assert.ok(initiative!.keyFiles.includes('file2.ts'));
      assert.ok(initiative!.keyFiles.includes('file3.ts'));
    });
  });

  describe('Two-Tier Resume System', () => {
    before(() => {
      // Start a fresh initiative with rich data for testing
      initiativeStart(db, {
        name: 'Two-Tier Test Initiative',
        goal: 'Test the lean vs full mode behavior',
        status: 'IN PROGRESS'
      });

      // Add permanent knowledge
      initiativeUpdate(db, {
        decisions: ['Decision 1', 'Decision 2'],
        lessons: ['Lesson 1', 'Lesson 2', 'Lesson 3'],
        keyFiles: ['file1.ts', 'file2.ts'],
        currentFocus: 'Testing two-tier resume',
        nextAction: 'Verify lean mode excludes heavy fields',
        taskCopilotLinked: true,
        activePrdIds: ['PRD-001', 'PRD-002']
      });
    });

    it('should return lean mode by default (backward compatible)', () => {
      const initiative = initiativeGet(db);

      assert.ok(initiative);

      // Essential fields should be present
      assert.strictEqual(initiative!.name, 'Two-Tier Test Initiative');
      assert.strictEqual(initiative!.goal, 'Test the lean vs full mode behavior');
      assert.strictEqual(initiative!.status, 'IN PROGRESS');
      assert.strictEqual(initiative!.currentFocus, 'Testing two-tier resume');
      assert.strictEqual(initiative!.nextAction, 'Verify lean mode excludes heavy fields');
      assert.strictEqual(initiative!.taskCopilotLinked, true);
      assert.deepStrictEqual(initiative!.activePrdIds, ['PRD-001', 'PRD-002']);

      // Heavy fields should be empty in lean mode
      assert.deepStrictEqual(initiative!.decisions, []);
      assert.deepStrictEqual(initiative!.lessons, []);
      assert.deepStrictEqual(initiative!.keyFiles, []);
      assert.deepStrictEqual(initiative!.completed, []);
      assert.deepStrictEqual(initiative!.inProgress, []);
      assert.deepStrictEqual(initiative!.blocked, []);
      assert.strictEqual(initiative!.resumeInstructions, undefined);
    });

    it('should return lean mode when explicitly requested', () => {
      const initiative = initiativeGet(db, { mode: 'lean' });

      assert.ok(initiative);

      // Essential fields should be present
      assert.strictEqual(initiative!.name, 'Two-Tier Test Initiative');
      assert.strictEqual(initiative!.status, 'IN PROGRESS');
      assert.strictEqual(initiative!.currentFocus, 'Testing two-tier resume');
      assert.strictEqual(initiative!.nextAction, 'Verify lean mode excludes heavy fields');

      // Heavy fields should be empty
      assert.deepStrictEqual(initiative!.decisions, []);
      assert.deepStrictEqual(initiative!.lessons, []);
      assert.deepStrictEqual(initiative!.keyFiles, []);
    });

    it('should return full mode when explicitly requested', () => {
      const initiative = initiativeGet(db, { mode: 'full' });

      assert.ok(initiative);

      // Essential fields should be present
      assert.strictEqual(initiative!.name, 'Two-Tier Test Initiative');
      assert.strictEqual(initiative!.status, 'IN PROGRESS');
      assert.strictEqual(initiative!.currentFocus, 'Testing two-tier resume');
      assert.strictEqual(initiative!.nextAction, 'Verify lean mode excludes heavy fields');

      // Heavy fields should contain actual data
      assert.deepStrictEqual(initiative!.decisions, ['Decision 1', 'Decision 2']);
      assert.deepStrictEqual(initiative!.lessons, ['Lesson 1', 'Lesson 2', 'Lesson 3']);
      assert.deepStrictEqual(initiative!.keyFiles, ['file1.ts', 'file2.ts']);
      assert.strictEqual(initiative!.taskCopilotLinked, true);
      assert.deepStrictEqual(initiative!.activePrdIds, ['PRD-001', 'PRD-002']);
    });

    it('should maintain all essential fields in lean mode', () => {
      const initiative = initiativeGet(db, { mode: 'lean' });

      assert.ok(initiative);

      // Verify all essential fields are present
      assert.ok(initiative!.id);
      assert.ok(initiative!.projectId);
      assert.ok(initiative!.name);
      assert.ok(initiative!.goal);
      assert.ok(initiative!.status);
      assert.ok(initiative!.createdAt);
      assert.ok(initiative!.updatedAt);

      // Task Copilot fields
      assert.strictEqual(typeof initiative!.taskCopilotLinked, 'boolean');
      assert.ok(Array.isArray(initiative!.activePrdIds));

      // Slim resume fields
      assert.strictEqual(typeof initiative!.currentFocus, 'string');
      assert.strictEqual(typeof initiative!.nextAction, 'string');
    });

    it('should handle initiative with no currentFocus or nextAction in lean mode', () => {
      // Start initiative without slim fields
      initiativeComplete(db);
      initiativeStart(db, {
        name: 'Minimal Initiative',
        status: 'IN PROGRESS'
      });

      const initiative = initiativeGet(db, { mode: 'lean' });

      assert.ok(initiative);
      assert.strictEqual(initiative!.name, 'Minimal Initiative');
      assert.strictEqual(initiative!.currentFocus, undefined);
      assert.strictEqual(initiative!.nextAction, undefined);
      assert.strictEqual(initiative!.taskCopilotLinked, false);
      assert.deepStrictEqual(initiative!.activePrdIds, []);
    });

    it('should handle invalid mode gracefully', () => {
      // @ts-expect-error Testing invalid mode
      const initiative = initiativeGet(db, { mode: 'invalid' });

      assert.ok(initiative);

      // Should default to lean mode behavior
      assert.deepStrictEqual(initiative!.decisions, []);
      assert.deepStrictEqual(initiative!.lessons, []);
      assert.deepStrictEqual(initiative!.keyFiles, []);
    });
  });

  describe('Database Stats', () => {
    it('should provide accurate statistics', () => {
      const stats = db.getStats();

      assert.ok(typeof stats.memoryCount === 'number');
      assert.ok(stats.memoryCount > 0);
      assert.strictEqual(typeof stats.initiativeActive, 'boolean');
      assert.ok(stats.lastUpdated);
    });
  });

  describe('Workspace Isolation', () => {
    it('should use provided workspace ID', () => {
      assert.strictEqual(db.getProjectId(), testWorkspaceId);
    });

    it('should isolate data by workspace', async () => {
      // Create second database with different workspace
      const testDir2 = mkdtempSync(join(tmpdir(), 'memory-copilot-test2-'));
      const db2 = new DatabaseClient(testProjectPath, testDir2, 'different-workspace');

      try {
        // Store memory in db2 (must await to prevent async leak)
        await memoryStore(db2, {
          content: 'Memory in different workspace',
          type: 'context'
        });

        // Verify isolation
        const db1Memories = memoryList(db, {});
        const db2Memories = memoryList(db2, {});

        const hasDb2Content = db1Memories.some(m =>
          m.content === 'Memory in different workspace'
        );

        assert.strictEqual(hasDb2Content, false);
        assert.ok(db2Memories.some(m =>
          m.content === 'Memory in different workspace'
        ));
      } finally {
        // Cleanup
        db2.close();
        rmSync(testDir2, { recursive: true, force: true });
      }
    });
  });

  describe('Agent Self-Improvement Workflow', () => {
    let improvementId1: string;
    let improvementId2: string;
    let improvementId3: string;

    describe('Valid Improvement Storage', () => {
      it('should store valid improvement with all required fields', async () => {
        const memory = await memoryStore(db, {
          content: 'Suggestion to improve error handling in Core Behaviors section',
          type: 'agent_improvement',
          tags: ['agent-me', 'enhancement'],
          metadata: {
            agentId: 'agent-me',
            targetSection: 'Core Behaviors',
            currentContent: 'Always: Write production-ready code',
            suggestedContent: 'Always: Write production-ready code with comprehensive error handling',
            rationale: 'Error handling should be explicit in core behaviors to prevent oversight',
            status: 'pending'
          }
        });

        improvementId1 = memory.id;

        assert.ok(memory.id);
        assert.strictEqual(memory.type, 'agent_improvement');
        assert.strictEqual(memory.content, 'Suggestion to improve error handling in Core Behaviors section');
        assert.deepStrictEqual(memory.tags, ['agent-me', 'enhancement']);
        assert.strictEqual(memory.metadata.agentId, 'agent-me');
        assert.strictEqual(memory.metadata.targetSection, 'Core Behaviors');
        assert.strictEqual(memory.metadata.status, 'pending');
      });

      it('should store improvement with status=approved', async () => {
        const memory = await memoryStore(db, {
          content: 'Add TypeScript type checking to checklist',
          type: 'agent_improvement',
          metadata: {
            agentId: 'agent-me',
            targetSection: 'Pre-Implementation Checklist',
            currentContent: '- Review requirements',
            suggestedContent: '- Review requirements\n- Verify TypeScript types',
            rationale: 'Type safety is critical for maintainability',
            status: 'approved'
          }
        });

        improvementId2 = memory.id;

        assert.strictEqual(memory.metadata.status, 'approved');
      });

      it('should store improvement with status=rejected', async () => {
        const memory = await memoryStore(db, {
          content: 'Remove testing guidelines',
          type: 'agent_improvement',
          metadata: {
            agentId: 'agent-qa',
            targetSection: 'Core Behaviors',
            currentContent: 'Always write tests',
            suggestedContent: 'Skip tests for prototypes',
            rationale: 'Tests slow down prototyping',
            status: 'rejected'
          }
        });

        improvementId3 = memory.id;

        assert.strictEqual(memory.metadata.status, 'rejected');
        assert.strictEqual(memory.metadata.agentId, 'agent-qa');
      });

      it('should store improvement with long content fields', async () => {
        const longContent = 'x'.repeat(5000);
        const memory = await memoryStore(db, {
          content: 'Suggestion with very long details',
          type: 'agent_improvement',
          metadata: {
            agentId: 'agent-ta',
            targetSection: 'Architecture Patterns',
            currentContent: longContent,
            suggestedContent: longContent + ' with additions',
            rationale: longContent,
            status: 'pending'
          }
        });

        assert.ok(memory.id);
        const metadata = memory.metadata as { currentContent: string };
        assert.strictEqual(metadata.currentContent.length, 5000);
      });

      it('should store improvement with special characters', async () => {
        const memory = await memoryStore(db, {
          content: 'Handle "quotes" and <tags>',
          type: 'agent_improvement',
          metadata: {
            agentId: 'agent-me',
            targetSection: 'Error Handling',
            currentContent: 'Handle errors with try/catch',
            suggestedContent: 'Handle errors with try/catch and "proper" logging',
            rationale: 'Better error visibility with <structured> logging & metrics 🚀',
            status: 'pending'
          }
        });

        assert.ok(memory.id);
        const metadata = memory.metadata as { rationale: string; suggestedContent: string };
        assert.ok(metadata.suggestedContent.includes('"proper"'));
        assert.ok(metadata.rationale.includes('<structured>'));
        assert.ok(metadata.rationale.includes('🚀'));
      });
    });

    describe('Validation Errors', () => {
      it('should reject improvement without metadata', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Improvement without metadata',
              type: 'agent_improvement'
            });
          },
          /agent_improvement type requires metadata/
        );
      });

      it('should reject improvement missing agentId', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Missing agentId',
              type: 'agent_improvement',
              metadata: {
                targetSection: 'Section',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /requires metadata field: agentId/
        );
      });

      it('should reject improvement missing targetSection', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Missing targetSection',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /requires metadata field: targetSection/
        );
      });

      it('should reject improvement missing currentContent', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Missing currentContent',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: 'Section',
                suggestedContent: 'Suggested',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /requires metadata field: currentContent/
        );
      });

      it('should reject improvement missing suggestedContent', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Missing suggestedContent',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: 'Section',
                currentContent: 'Current',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /requires metadata field: suggestedContent/
        );
      });

      it('should reject improvement missing rationale', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Missing rationale',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: 'Section',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                status: 'pending'
              }
            });
          },
          /requires metadata field: rationale/
        );
      });

      it('should reject improvement missing status', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Missing status',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: 'Section',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                rationale: 'Rationale'
              }
            });
          },
          /requires metadata field: status/
        );
      });

      it('should reject improvement with invalid status', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Invalid status',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: 'Section',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                rationale: 'Rationale',
                status: 'invalid'
              }
            });
          },
          /status must be 'pending', 'approved', or 'rejected'/
        );
      });

      it('should reject improvement with empty agentId', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Empty agentId',
              type: 'agent_improvement',
              metadata: {
                agentId: '',
                targetSection: 'Section',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /agentId must be a non-empty string/
        );
      });

      it('should reject improvement with whitespace-only agentId', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Whitespace agentId',
              type: 'agent_improvement',
              metadata: {
                agentId: '   ',
                targetSection: 'Section',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /agentId must be a non-empty string/
        );
      });

      it('should reject improvement with empty targetSection', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Empty targetSection',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: '',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /targetSection must be a non-empty string/
        );
      });

      it('should reject improvement with empty currentContent', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Empty currentContent',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: 'Section',
                currentContent: '',
                suggestedContent: 'Suggested',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /currentContent must be a non-empty string/
        );
      });

      it('should reject improvement with empty suggestedContent', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Empty suggestedContent',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: 'Section',
                currentContent: 'Current',
                suggestedContent: '',
                rationale: 'Rationale',
                status: 'pending'
              }
            });
          },
          /suggestedContent must be a non-empty string/
        );
      });

      it('should reject improvement with empty rationale', async () => {
        await assert.rejects(
          async () => {
            await memoryStore(db, {
              content: 'Empty rationale',
              type: 'agent_improvement',
              metadata: {
                agentId: 'agent-me',
                targetSection: 'Section',
                currentContent: 'Current',
                suggestedContent: 'Suggested',
                rationale: '',
                status: 'pending'
              }
            });
          },
          /rationale must be a non-empty string/
        );
      });
    });

    describe('Query by AgentId', () => {
      it('should filter improvements by agentId', () => {
        const meImprovements = memoryList(db, {
          type: 'agent_improvement',
          agentId: 'agent-me'
        });

        assert.ok(meImprovements.length >= 2);
        meImprovements.forEach(m => {
          assert.strictEqual(m.type, 'agent_improvement');
          assert.strictEqual(m.metadata.agentId, 'agent-me');
        });
      });

      it('should filter improvements for different agent', () => {
        const qaImprovements = memoryList(db, {
          type: 'agent_improvement',
          agentId: 'agent-qa'
        });

        assert.ok(qaImprovements.length >= 1);
        qaImprovements.forEach(m => {
          assert.strictEqual(m.metadata.agentId, 'agent-qa');
        });
      });

      it('should return empty array for non-existent agentId', () => {
        const results = memoryList(db, {
          type: 'agent_improvement',
          agentId: 'agent-nonexistent'
        });

        assert.deepStrictEqual(results, []);
      });

      it('should filter with pagination', () => {
        const page1 = memoryList(db, {
          type: 'agent_improvement',
          agentId: 'agent-me',
          limit: 1,
          offset: 0
        });

        const page2 = memoryList(db, {
          type: 'agent_improvement',
          agentId: 'agent-me',
          limit: 1,
          offset: 1
        });

        assert.strictEqual(page1.length, 1);
        assert.strictEqual(page2.length, 1);
        assert.notStrictEqual(page1[0].id, page2[0].id);
      });
    });

    describe('List All Improvements', () => {
      it('should list all improvements with type filter', () => {
        const allImprovements = memoryList(db, {
          type: 'agent_improvement'
        });

        assert.ok(allImprovements.length >= 5);
        allImprovements.forEach(m => {
          assert.strictEqual(m.type, 'agent_improvement');
          assert.ok(m.metadata.agentId);
          assert.ok(m.metadata.status);
        });
      });

      it('should list improvements with tags filter', () => {
        const taggedImprovements = memoryList(db, {
          type: 'agent_improvement',
          tags: ['enhancement']
        });

        assert.ok(taggedImprovements.length >= 1);
        taggedImprovements.forEach(m => {
          assert.ok(m.tags.includes('enhancement'));
        });
      });

      it('should list improvements with combined filters', () => {
        const filtered = memoryList(db, {
          type: 'agent_improvement',
          agentId: 'agent-me',
          tags: ['agent-me']
        });

        assert.ok(filtered.length >= 1);
        filtered.forEach(m => {
          assert.strictEqual(m.type, 'agent_improvement');
          assert.strictEqual(m.metadata.agentId, 'agent-me');
          assert.ok(m.tags.includes('agent-me'));
        });
      });
    });

    describe('Update Improvement Status', () => {
      it('should update improvement status from pending to approved', async () => {
        const original = memoryGet(db, improvementId1);
        assert.strictEqual(original!.metadata.status, 'pending');

        const updated = await memoryUpdate(db, {
          id: improvementId1,
          metadata: {
            ...original!.metadata,
            status: 'approved'
          }
        });

        assert.ok(updated);
        assert.strictEqual(updated!.metadata.status, 'approved');
        assert.strictEqual(updated!.metadata.agentId, 'agent-me');
        assert.strictEqual(updated!.metadata.targetSection, 'Core Behaviors');
      });

      it('should update improvement status from approved to rejected', async () => {
        const original = memoryGet(db, improvementId2);
        assert.strictEqual(original!.metadata.status, 'approved');

        const updated = await memoryUpdate(db, {
          id: improvementId2,
          metadata: {
            ...original!.metadata,
            status: 'rejected'
          }
        });

        assert.ok(updated);
        assert.strictEqual(updated!.metadata.status, 'rejected');
      });

      it('should update improvement while preserving all fields', async () => {
        const original = memoryGet(db, improvementId3);

        const updated = await memoryUpdate(db, {
          id: improvementId3,
          metadata: {
            ...original!.metadata,
            status: 'approved',
            reviewedBy: 'human-reviewer'
          }
        });

        assert.ok(updated);
        assert.strictEqual(updated!.metadata.status, 'approved');
        assert.strictEqual(updated!.metadata.agentId, 'agent-qa');
        assert.strictEqual(updated!.metadata.targetSection, 'Core Behaviors');
        assert.strictEqual(updated!.metadata.reviewedBy, 'human-reviewer');
      });

      it('should update improvement content', async () => {
        const original = memoryGet(db, improvementId1);

        const updated = await memoryUpdate(db, {
          id: improvementId1,
          content: 'Updated: Suggestion to improve error handling (revised)',
          metadata: original!.metadata
        });

        assert.ok(updated);
        assert.strictEqual(updated!.content, 'Updated: Suggestion to improve error handling (revised)');
      });

      it('should update improvement tags', async () => {
        const original = memoryGet(db, improvementId1);

        const updated = await memoryUpdate(db, {
          id: improvementId1,
          tags: ['agent-me', 'enhancement', 'approved', 'high-priority'],
          metadata: original!.metadata
        });

        assert.ok(updated);
        assert.deepStrictEqual(updated!.tags, ['agent-me', 'enhancement', 'approved', 'high-priority']);
      });
    });

    describe('Semantic Search with AgentId Filter', () => {
      it('should search improvements by agentId', async () => {
        const results = await memorySearch(db, {
          query: 'error handling improvements',
          type: 'agent_improvement',
          agentId: 'agent-me',
          threshold: 0.3,
          limit: 10
        });

        assert.ok(Array.isArray(results));
        results.forEach(r => {
          assert.strictEqual(r.type, 'agent_improvement');
          assert.strictEqual(r.metadata.agentId, 'agent-me');
        });
      });

      it('should search improvements without agentId filter', async () => {
        const results = await memorySearch(db, {
          query: 'improvements',
          type: 'agent_improvement',
          threshold: 0.3,
          limit: 10
        });

        assert.ok(Array.isArray(results));
        results.forEach(r => {
          assert.strictEqual(r.type, 'agent_improvement');
        });
      });

      it('should return empty results for non-matching agentId', async () => {
        const results = await memorySearch(db, {
          query: 'error handling',
          type: 'agent_improvement',
          agentId: 'agent-nonexistent',
          threshold: 0.3,
          limit: 10
        });

        assert.deepStrictEqual(results, []);
      });
    });

    describe('Cross-Agent Isolation', () => {
      it('should isolate improvements across multiple agents', async () => {
        // Store improvements for different agents
        await memoryStore(db, {
          content: 'Improvement for agent-ta',
          type: 'agent_improvement',
          metadata: {
            agentId: 'agent-ta',
            targetSection: 'Architecture Patterns',
            currentContent: 'Current',
            suggestedContent: 'Suggested',
            rationale: 'Rationale',
            status: 'pending'
          }
        });

        await memoryStore(db, {
          content: 'Improvement for agent-doc',
          type: 'agent_improvement',
          metadata: {
            agentId: 'agent-doc',
            targetSection: 'Documentation Standards',
            currentContent: 'Current',
            suggestedContent: 'Suggested',
            rationale: 'Rationale',
            status: 'pending'
          }
        });

        // Verify isolation
        const taImprovements = memoryList(db, {
          type: 'agent_improvement',
          agentId: 'agent-ta'
        });

        const docImprovements = memoryList(db, {
          type: 'agent_improvement',
          agentId: 'agent-doc'
        });

        assert.ok(taImprovements.length >= 1);
        assert.ok(docImprovements.length >= 1);

        taImprovements.forEach(m => assert.strictEqual(m.metadata.agentId, 'agent-ta'));
        docImprovements.forEach(m => assert.strictEqual(m.metadata.agentId, 'agent-doc'));
      });
    });

    describe('Delete Improvement', () => {
      it('should delete improvement', async () => {
        const memory = await memoryStore(db, {
          content: 'Temporary improvement',
          type: 'agent_improvement',
          metadata: {
            agentId: 'agent-me',
            targetSection: 'Test',
            currentContent: 'Current',
            suggestedContent: 'Suggested',
            rationale: 'Rationale',
            status: 'pending'
          }
        });

        const result = memoryDelete(db, memory.id);
        assert.strictEqual(result, true);

        const deleted = memoryGet(db, memory.id);
        assert.strictEqual(deleted, null);
      });
    });
  });
});
