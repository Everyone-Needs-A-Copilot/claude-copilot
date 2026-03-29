#!/usr/bin/env node

/**
 * Mark all implemented P1 enhancement tasks as complete
 *
 * Usage: node mark-tasks-complete.mjs
 */

import { DatabaseClient } from './mcp-servers/task-copilot/dist/database.js';
import { taskUpdate } from './mcp-servers/task-copilot/dist/tools/task.js';
import { homedir } from 'os';
import { join } from 'path';

// Use the same configuration as .mcp.json
const TASK_DB_PATH = join(homedir(), '.claude', 'tasks');
const WORKSPACE_ID = 'claude-copilot';

// All subtasks that are now complete
const completedSubtasks = [
  // Verification Enforcement (4 subtasks - 20 tests passing)
  'TASK-eafbf4d2-3c0e-42f7-8e58-17dd1c862272', // Add validation rule for acceptanceCriteria
  'TASK-c761e325-2ad4-4046-b692-702025904e37', // Add proof validation for task completion
  'TASK-c31a22b4-8326-481e-9980-986c7b545625', // Update task_update to enforce verification
  'TASK-c18efc27-9d42-48fb-a3d5-93fae1987484', // Add tests for verification enforcement

  // Pause/Resume (4 subtasks - 15 tests passing)
  'TASK-e50d3b86-f84e-4cb8-859f-86f9987c71d6', // Create /pause command
  'TASK-1df59ae8-544e-4ee4-9bea-7ad59fe6abec', // Enhance /continue with checkpoint detection
  'TASK-7635be67-5c3e-495f-a9fc-188b37e8a56a', // Add checkpoint metadata enhancements
  'TASK-364aa677-f48b-4500-9509-77f0e054e7b1', // Add tests for pause/resume flow

  // Activation Modes (4 subtasks - 16 tests passing)
  'TASK-eaac83a9-15ba-41bb-8a79-3dd80c16c60d', // Add activationMode validation rule
  'TASK-e68544ae-81e9-43fd-8d71-b2b4be3e62df', // Implement mode auto-detection
  'TASK-c59cb938-4bc9-4770-9a7d-a6d273896ea1', // Integrate activation modes with task_create
  'TASK-7d71c5f4-1aa0-4a3c-8983-f742b6c28a57', // Add tests for activation modes

  // Progress Visibility (5 subtasks - 22 tests passing)
  'TASK-dee92657-fe1c-4ec9-bb0e-81fef4e51ff4', // Add milestones to PRD metadata
  'TASK-7e7158f8-4a8a-4edf-b6e1-bdcc0ef925fc', // Enhance progress_summary with milestones
  'TASK-7d449710-0e02-4ca0-a866-c40af8cd2ab2', // Add ASCII progress bar utility
  'TASK-fc35b6d5-6637-46ea-b986-2f79539d7d88', // Add velocity trend calculation
  'TASK-4c0104de-5a4e-4069-bed4-dbffbef2e98e', // Add tests for progress visibility

  // Auto-commit (1 task - 7 tests passing)
  'TASK-419ae33f-a31b-4ef9-832f-b813bee8035b'  // P1.2: Implement auto-commit on task completion
];

// Parent tasks that should also be marked complete
const completedParents = [
  'TASK-23d1befb-2a5f-4bc0-afff-09d3a64f92fe', // Implement Verification Enforcement
  'TASK-462b4ec0-cdf6-4a60-afa2-04038b06498d', // Implement Enhanced Pause/Resume
  'TASK-fc08a7f2-32e6-4b9d-824c-5ead2676b335', // Implement Atomic Execution Modes
  'TASK-93404e26-1d8f-4006-b064-c0f32a764570'  // Implement Progress Visibility Enhancements
];

async function main() {
  console.log('Marking P1 enhancement tasks as complete...\n');

  const db = new DatabaseClient(
    process.cwd(),
    TASK_DB_PATH,
    WORKSPACE_ID
  );

  let successCount = 0;
  let errorCount = 0;

  // Mark subtasks as complete
  console.log('Updating subtasks:');
  for (const taskId of completedSubtasks) {
    try {
      const result = await taskUpdate(db, {
        id: taskId,
        status: 'completed',
        notes: 'Implementation verified via passing test suite'
      });

      if (result) {
        console.log(`  ✓ ${taskId}`);
        successCount++;
      } else {
        console.log(`  ⚠ ${taskId} - not found or already completed`);
      }
    } catch (error) {
      console.error(`  ✗ ${taskId} - ${error.message}`);
      errorCount++;
    }
  }

  // Mark parent tasks as complete
  console.log('\nUpdating parent tasks:');
  for (const taskId of completedParents) {
    try {
      const result = await taskUpdate(db, {
        id: taskId,
        status: 'completed',
        notes: 'All subtasks completed and verified via passing tests'
      });

      if (result) {
        console.log(`  ✓ ${taskId}`);
        successCount++;
      } else {
        console.log(`  ⚠ ${taskId} - not found or already completed`);
      }
    } catch (error) {
      console.error(`  ✗ ${taskId} - ${error.message}`);
      errorCount++;
    }
  }

  console.log(`\n=== Summary ===`);
  console.log(`Total tasks processed: ${completedSubtasks.length + completedParents.length}`);
  console.log(`Successfully updated: ${successCount}`);
  console.log(`Errors: ${errorCount}`);

  db.close();

  if (errorCount > 0) {
    process.exit(1);
  }
}

main().catch(error => {
  console.error('Fatal error:', error);
  process.exit(1);
});
