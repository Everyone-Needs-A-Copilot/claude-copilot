/**
 * Correction Storage Tools
 *
 * MCP tool implementations for storing and managing corrections
 * in the two-stage correction workflow.
 *
 * @see PRD-6df7cc11-c4d4-4f48-9e0c-1275cf6fb327
 */

import type { DatabaseClient } from '../db/client.js';
import type {
  CorrectionCapture,
  CorrectionRow,
  CorrectionStatus,
  CorrectionTarget,
  CorrectionReviewDecision,
  CorrectionStats,
  ReflectSummary,
} from '../types/corrections.js';

/**
 * Convert CorrectionCapture to CorrectionRow for storage
 */
function captureToRow(capture: CorrectionCapture): Omit<CorrectionRow, 'project_id'> {
  return {
    id: capture.id,
    session_id: capture.sessionId || null,
    task_id: capture.taskId || null,
    agent_id: capture.agentId || null,
    original_content: capture.originalContent,
    corrected_content: capture.correctedContent,
    raw_user_message: capture.rawUserMessage,
    matched_patterns: JSON.stringify(capture.matchedPatterns),
    extracted_what: capture.extractedWhat || null,
    extracted_why: capture.extractedWhy || null,
    extracted_how: capture.extractedHow || null,
    target: capture.target,
    target_id: capture.targetId || null,
    target_section: capture.targetSection || null,
    confidence: capture.confidence,
    status: capture.status,
    created_at: capture.createdAt,
    updated_at: capture.updatedAt,
    reviewed_at: capture.reviewedAt || null,
    applied_at: capture.appliedAt || null,
    expires_at: capture.expiresAt || null,
    review_metadata: capture.reviewMetadata ? JSON.stringify(capture.reviewMetadata) : null,
  };
}

/**
 * Convert CorrectionRow to CorrectionCapture
 */
function rowToCapture(row: CorrectionRow): CorrectionCapture {
  return {
    id: row.id,
    projectId: row.project_id,
    sessionId: row.session_id || undefined,
    taskId: row.task_id || undefined,
    agentId: row.agent_id || undefined,
    originalContent: row.original_content,
    correctedContent: row.corrected_content,
    rawUserMessage: row.raw_user_message,
    matchedPatterns: JSON.parse(row.matched_patterns || '[]'),
    extractedWhat: row.extracted_what || undefined,
    extractedWhy: row.extracted_why || undefined,
    extractedHow: row.extracted_how || undefined,
    target: row.target as CorrectionTarget,
    targetId: row.target_id || undefined,
    targetSection: row.target_section || undefined,
    confidence: row.confidence,
    status: row.status as CorrectionStatus,
    createdAt: row.created_at,
    updatedAt: row.updated_at,
    reviewedAt: row.reviewed_at || undefined,
    appliedAt: row.applied_at || undefined,
    expiresAt: row.expires_at || undefined,
    reviewMetadata: row.review_metadata ? JSON.parse(row.review_metadata) : undefined,
  };
}

/**
 * Store a correction capture
 */
export function correctionStore(
  db: DatabaseClient,
  capture: CorrectionCapture
): { id: string; stored: boolean } {
  try {
    // Set project ID
    capture.projectId = db.getProjectId();

    const row = captureToRow(capture);
    db.insertCorrection(row);

    return { id: capture.id, stored: true };
  } catch (error) {
    console.error('Failed to store correction:', error);
    return { id: capture.id, stored: false };
  }
}

/**
 * Get a correction by ID
 */
export function correctionGet(
  db: DatabaseClient,
  id: string
): CorrectionCapture | null {
  const row = db.getCorrection(id);
  if (!row) return null;
  return rowToCapture(row);
}

/**
 * List corrections with filters
 */
export function correctionList(
  db: DatabaseClient,
  options: {
    status?: CorrectionStatus;
    agentId?: string;
    target?: CorrectionTarget;
    limit?: number;
    offset?: number;
    includeExpired?: boolean;
  }
): CorrectionCapture[] {
  // First, expire old corrections
  db.expireCorrections();

  const rows = db.listCorrections(options);
  return rows.map(rowToCapture);
}

/**
 * Review a correction (approve, reject, or modify)
 */
export function correctionReview(
  db: DatabaseClient,
  decision: CorrectionReviewDecision
): { success: boolean; correction?: CorrectionCapture; error?: string } {
  const existing = db.getCorrection(decision.correctionId);
  if (!existing) {
    return { success: false, error: 'Correction not found' };
  }

  if (existing.status !== 'pending') {
    return { success: false, error: `Correction already ${existing.status}` };
  }

  const now = new Date().toISOString();
  const updates: Partial<CorrectionRow> = {
    reviewed_at: now,
    review_metadata: JSON.stringify({
      reviewedBy: 'user',
      rejectionReason: decision.rejectionReason,
      modifiedBefore: decision.decision === 'modify' ? existing.corrected_content : undefined,
      modifiedAfter: decision.modifiedContent,
      notes: decision.notes,
    }),
  };

  switch (decision.decision) {
    case 'approve':
      updates.status = 'approved';
      break;
    case 'reject':
      updates.status = 'rejected';
      break;
    case 'modify':
      updates.status = 'approved';
      if (decision.modifiedContent) {
        updates.corrected_content = decision.modifiedContent;
      }
      break;
  }

  const success = db.updateCorrection(decision.correctionId, updates);
  if (!success) {
    return { success: false, error: 'Failed to update correction' };
  }

  const updated = db.getCorrection(decision.correctionId);
  return {
    success: true,
    correction: updated ? rowToCapture(updated) : undefined,
  };
}

/**
 * Delete a correction
 */
export function correctionDelete(
  db: DatabaseClient,
  id: string
): boolean {
  return db.deleteCorrection(id);
}

/**
 * Get correction statistics
 */
export function correctionStats(db: DatabaseClient): CorrectionStats {
  const stats = db.getCorrectionStats();

  // Calculate additional stats
  const approved = stats.byStatus.approved || 0;
  const rejected = stats.byStatus.rejected || 0;
  const applied = stats.byStatus.applied || 0;
  const totalReviewed = approved + rejected;

  return {
    total: stats.total,
    byStatus: stats.byStatus,
    byTarget: stats.byTarget,
    byAgent: stats.byAgent,
    avgApprovedConfidence: 0, // Would need additional query to calculate
    falsePositiveRate: totalReviewed > 0 ? rejected / totalReviewed : 0,
    applicationSuccessRate: approved > 0 ? applied / approved : 0,
    topPatterns: [], // Would need additional aggregation
  };
}

/**
 * Get summary for /reflect command
 */
export function getReflectSummary(
  db: DatabaseClient,
  options: {
    limit?: number;
    agentId?: string;
  } = {}
): ReflectSummary {
  // Expire old corrections first
  db.expireCorrections();

  const stats = db.getCorrectionStats();

  // Get pending corrections
  const pending = db.listCorrections({
    status: 'pending',
    agentId: options.agentId,
    limit: options.limit || 10,
  });

  // Get recently applied
  const applied = db.listCorrections({
    status: 'applied',
    agentId: options.agentId,
    limit: 5,
  });

  return {
    totalCaptured: stats.total,
    byStatus: stats.byStatus,
    byTarget: stats.byTarget,
    byAgent: stats.byAgent,
    pendingReview: pending.map(rowToCapture),
    recentlyApplied: applied.map(rowToCapture),
  };
}

/**
 * Mark a correction as applied
 */
export function correctionMarkApplied(
  db: DatabaseClient,
  id: string
): { success: boolean; error?: string } {
  const existing = db.getCorrection(id);
  if (!existing) {
    return { success: false, error: 'Correction not found' };
  }

  if (existing.status !== 'approved') {
    return { success: false, error: `Cannot mark as applied: status is ${existing.status}, expected approved` };
  }

  const success = db.updateCorrection(id, {
    status: 'applied',
    applied_at: new Date().toISOString(),
  });

  return { success };
}
