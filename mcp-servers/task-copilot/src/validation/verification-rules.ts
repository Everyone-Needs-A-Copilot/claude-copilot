/**
 * Verification enforcement rules for task completion
 *
 * GSD-inspired DX improvement: Blocks task completion without success criteria and proof
 */

import type { TaskRow, TaskMetadata } from '../types.js';
import type { DatabaseClient } from '../database.js';

export interface VerificationResult {
  allowed: boolean;
  flags: Array<{
    type: 'acceptance_criteria' | 'proof';
    severity: 'reject';
    message: string;
    suggestion: string;
  }>;
  actionableFeedback?: string;
}

/**
 * Check if task requires verification enforcement
 */
export function requiresVerification(task: TaskRow): boolean {
  try {
    const metadata = JSON.parse(task.metadata) as TaskMetadata;
    return metadata.verificationRequired === true;
  } catch {
    return false;
  }
}

/**
 * Validate task has acceptance criteria
 */
function validateAcceptanceCriteria(task: TaskRow): VerificationResult['flags'][number] | null {
  try {
    const metadata = JSON.parse(task.metadata) as TaskMetadata;

    // Check if acceptanceCriteria exists and is non-empty
    if (!metadata.acceptanceCriteria || metadata.acceptanceCriteria.length === 0) {
      return {
        type: 'acceptance_criteria',
        severity: 'reject',
        message: 'Task missing acceptance criteria',
        suggestion: 'Add acceptanceCriteria to task metadata before marking as completed. Example: metadata.acceptanceCriteria = ["Test passes", "Code reviewed"]'
      };
    }

    return null;
  } catch {
    return {
      type: 'acceptance_criteria',
      severity: 'reject',
      message: 'Failed to parse task metadata',
      suggestion: 'Ensure task metadata is valid JSON'
    };
  }
}

/**
 * Validate task has proof/evidence
 *
 * Proof can be:
 * - Work products attached to task
 * - Notes documenting test results
 * - Blocked reason (if blocked, that's the proof)
 */
function validateProof(db: DatabaseClient, task: TaskRow): VerificationResult['flags'][number] | null {
  // Check for work products
  const hasWorkProducts = db.hasWorkProducts(task.id);
  if (hasWorkProducts) {
    return null; // Work product is valid proof
  }

  // Check for notes with substantive content (>50 chars)
  if (task.notes && task.notes.trim().length >= 50) {
    return null; // Substantive notes are valid proof
  }

  // Check for blocked reason (if task is being marked as blocked, that's documented)
  if (task.blocked_reason && task.blocked_reason.trim().length > 0) {
    return null; // Blocked reason is valid proof
  }

  // No proof found
  return {
    type: 'proof',
    severity: 'reject',
    message: 'Task completion requires proof/evidence',
    suggestion: 'Provide evidence of completion via: (1) work_product_store with test results/implementation, (2) task notes documenting what was done (min 50 chars), or (3) blocked_reason if task cannot be completed'
  };
}

/**
 * Validate task completion requirements
 *
 * Only enforced when:
 * - Task has verificationRequired=true in metadata
 * - Task is being marked as 'completed'
 */
export function validateTaskCompletion(
  db: DatabaseClient,
  task: TaskRow
): VerificationResult {
  const flags: VerificationResult['flags'] = [];

  // Check acceptance criteria
  const criteriaFlag = validateAcceptanceCriteria(task);
  if (criteriaFlag) {
    flags.push(criteriaFlag);
  }

  // Check proof/evidence
  const proofFlag = validateProof(db, task);
  if (proofFlag) {
    flags.push(proofFlag);
  }

  // Generate actionable feedback
  const actionableFeedback = flags.length > 0
    ? generateFeedback(flags)
    : undefined;

  return {
    allowed: flags.length === 0,
    flags,
    actionableFeedback
  };
}

/**
 * Generate human-readable feedback from validation flags
 */
function generateFeedback(flags: VerificationResult['flags']): string {
  const lines = ['Verification failed - task cannot be completed:'];

  for (const flag of flags) {
    lines.push(`\n[${flag.type.toUpperCase()}] ${flag.message}`);
    lines.push(`  → ${flag.suggestion}`);
  }

  lines.push('\nThis verification is required because task has verificationRequired=true in metadata.');
  lines.push('To disable verification, set metadata.verificationRequired=false or remove the field.');

  return lines.join('\n');
}
