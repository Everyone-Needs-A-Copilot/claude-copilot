/**
 * Activation Mode Validation Rules
 *
 * Validates task structure based on activation mode (ultrawork, analyze, quick, thorough)
 * Enforces GSD-inspired constraints like the 3-subtask limit for ultrawork mode.
 */

import type { DatabaseClient } from '../database.js';
import type { TaskRow, TaskMetadata } from '../types.js';

export interface ActivationModeValidationResult {
  valid: boolean;
  warnings: string[];
  actionableFeedback?: string;
}

/**
 * Validate task structure against its activation mode constraints
 *
 * Current rules:
 * - ultrawork: Warn if >3 subtasks (GSD atomic work principle)
 * - analyze: No constraints yet
 * - quick: No constraints yet
 * - thorough: No constraints (explicitly allows complex work)
 *
 * @param db - Database client
 * @param task - Task to validate
 * @returns Validation result with warnings
 */
export function validateActivationMode(
  db: DatabaseClient,
  task: TaskRow
): ActivationModeValidationResult {
  const warnings: string[] = [];
  const metadata = JSON.parse(task.metadata) as TaskMetadata;
  const mode = metadata.activationMode;

  // No validation if mode is not set or is null
  if (!mode) {
    return { valid: true, warnings };
  }

  // Ultrawork mode: enforce 3-subtask limit
  if (mode === 'ultrawork') {
    const subtaskCounts = db.getTaskSubtaskCount(task.id);
    const totalSubtasks = subtaskCounts.total;

    if (totalSubtasks > 3) {
      const warning = buildUltraworkWarning(task.title, totalSubtasks);
      warnings.push(warning);
    }
  }

  // Future modes can add constraints here:
  // - analyze: Could warn if no investigation notes
  // - quick: Could warn if subtasks > 1
  // - thorough: No constraints (allows deep work)

  return {
    valid: true, // Warnings don't block operations
    warnings,
    actionableFeedback: warnings.length > 0 ? warnings.join('\n\n') : undefined
  };
}

/**
 * Build a clear warning message for ultrawork mode violations
 */
function buildUltraworkWarning(taskTitle: string, subtaskCount: number): string {
  return [
    `⚠️  ULTRAWORK MODE CONSTRAINT VIOLATED`,
    ``,
    `Task: "${taskTitle}"`,
    `Subtasks: ${subtaskCount} (limit: 3)`,
    ``,
    `Ultrawork mode enforces atomic, focused work with max 3 subtasks.`,
    ``,
    `Recommendations:`,
    `1. Break this task into smaller ultrawork tasks (preferred)`,
    `2. Change activationMode to "thorough" if complexity justified`,
    `3. Remove ${subtaskCount - 3} subtask(s) to fit within limit`,
    ``,
    `Why this matters: Tasks with >3 subtasks often indicate scope creep.`,
    `Smaller tasks → faster iteration → better focus → higher completion rate.`
  ].join('\n');
}

/**
 * Check if a task should be validated for activation mode
 * (Only validate tasks that have subtasks and an activation mode set)
 */
export function shouldValidateActivationMode(task: TaskRow): boolean {
  const metadata = JSON.parse(task.metadata) as TaskMetadata;
  return metadata.activationMode !== undefined && metadata.activationMode !== null;
}
