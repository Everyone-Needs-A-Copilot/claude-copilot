/**
 * Correction Routing Tool
 *
 * Routes approved corrections to appropriate targets:
 * - skill: Updates skill files
 * - agent: Stores as agent_improvement memory
 * - memory: Stores as lesson or decision
 * - preference: Stores as user preference
 *
 * @see PRD-6df7cc11-c4d4-4f48-9e0c-1275cf6fb327
 */

import type { DatabaseClient } from '../db/client.js';
import type {
  CorrectionCapture,
  CorrectionTarget,
  CorrectionRouteInput,
  CorrectionRouteOutput,
  CorrectionApplicationResult,
} from '../types/corrections.js';
import type { MemoryType } from '../types.js';
import { v4 as uuidv4 } from 'uuid';

// Agent mapping for correction routing
const AGENT_ROUTING_MAP: Record<string, string[]> = {
  // Code patterns and implementation
  me: ['code', 'implementation', 'pattern', 'style', 'syntax', 'function', 'class', 'variable'],
  // Documentation
  doc: ['documentation', 'readme', 'comment', 'docstring', 'jsdoc', 'api doc'],
  // Testing
  qa: ['test', 'spec', 'assertion', 'mock', 'fixture', 'coverage'],
  // Architecture
  ta: ['architecture', 'design', 'structure', 'pattern', 'system'],
  // Security
  sec: ['security', 'auth', 'permission', 'vulnerability', 'credential'],
  // DevOps
  do: ['deployment', 'ci', 'pipeline', 'docker', 'kubernetes', 'config'],
};

// Keywords for determining target type
const TARGET_KEYWORDS: Record<CorrectionTarget, string[]> = {
  skill: ['skill', 'workflow', 'process', 'methodology', 'approach', 'technique'],
  agent: ['agent', 'instruction', 'behavior', 'response', 'output'],
  memory: ['remember', 'decision', 'lesson', 'learned', 'context', 'fact'],
  preference: ['prefer', 'always', 'never', 'style', 'convention', 'format'],
};

/**
 * Determine the best target for a correction based on content analysis
 */
function determineTarget(correction: CorrectionCapture): {
  target: CorrectionTarget;
  targetId?: string;
  targetSection?: string;
  confidence: number;
} {
  const content = `${correction.rawUserMessage} ${correction.correctedContent}`.toLowerCase();
  const scores: Record<CorrectionTarget, number> = {
    skill: 0,
    agent: 0,
    memory: 0,
    preference: 0,
  };

  // Score based on keywords
  for (const [target, keywords] of Object.entries(TARGET_KEYWORDS)) {
    for (const keyword of keywords) {
      if (content.includes(keyword)) {
        scores[target as CorrectionTarget] += 1;
      }
    }
  }

  // If agent context exists, boost agent score
  if (correction.agentId) {
    scores.agent += 2;
  }

  // Find highest scoring target
  let bestTarget: CorrectionTarget = 'memory'; // default
  let bestScore = 0;

  for (const [target, score] of Object.entries(scores)) {
    if (score > bestScore) {
      bestScore = score;
      bestTarget = target as CorrectionTarget;
    }
  }

  // Determine target ID based on target type
  let targetId: string | undefined;
  let targetSection: string | undefined;

  if (bestTarget === 'agent' && correction.agentId) {
    targetId = correction.agentId;
    // Try to determine section from content
    if (content.includes('behavior') || content.includes('always') || content.includes('never')) {
      targetSection = 'Core Behaviors';
    } else if (content.includes('output') || content.includes('format')) {
      targetSection = 'Output format';
    }
  } else if (bestTarget === 'skill') {
    // Try to detect skill name from content
    const skillMatch = content.match(/skill[:\s]+([a-z0-9-]+)/i);
    if (skillMatch) {
      targetId = skillMatch[1];
    }
  }

  // Calculate confidence based on score strength
  const totalScore = Object.values(scores).reduce((a, b) => a + b, 0);
  const confidence = totalScore > 0 ? Math.min(0.95, 0.5 + (bestScore / totalScore) * 0.45) : 0.5;

  return {
    target: bestTarget,
    targetId,
    targetSection,
    confidence,
  };
}

/**
 * Determine which agent should handle a correction
 */
function determineAgent(correction: CorrectionCapture): string {
  // If agent context exists, use it
  if (correction.agentId) {
    return correction.agentId;
  }

  const content = `${correction.rawUserMessage} ${correction.correctedContent}`.toLowerCase();

  // Score each agent based on keywords
  const scores: Record<string, number> = {};

  for (const [agent, keywords] of Object.entries(AGENT_ROUTING_MAP)) {
    scores[agent] = 0;
    for (const keyword of keywords) {
      if (content.includes(keyword)) {
        scores[agent] += 1;
      }
    }
  }

  // Find highest scoring agent
  let bestAgent = 'me'; // default to implementation agent
  let bestScore = 0;

  for (const [agent, score] of Object.entries(scores)) {
    if (score > bestScore) {
      bestScore = score;
      bestAgent = agent;
    }
  }

  return bestAgent;
}

/**
 * Route a correction to its target
 */
export function correctionRoute(
  db: DatabaseClient,
  input: CorrectionRouteInput,
  sessionId: string
): CorrectionRouteOutput {
  // Get the correction
  const correction = db.getCorrection(input.correctionId);
  if (!correction) {
    throw new Error('Correction not found');
  }

  // Check status
  if (correction.status !== 'approved') {
    throw new Error(`Cannot route correction with status: ${correction.status}`);
  }

  // Determine target
  let target: CorrectionTarget;
  let targetId: string | undefined;
  let targetSection: string | undefined;
  let confidence: number;

  if (input.forceTarget) {
    target = input.forceTarget;
    targetId = input.forceTargetId;
    confidence = 1.0; // User-specified
  } else {
    const determined = determineTarget({
      id: correction.id,
      projectId: correction.project_id,
      sessionId: correction.session_id || undefined,
      taskId: correction.task_id || undefined,
      agentId: correction.agent_id || undefined,
      originalContent: correction.original_content,
      correctedContent: correction.corrected_content,
      rawUserMessage: correction.raw_user_message,
      matchedPatterns: JSON.parse(correction.matched_patterns || '[]'),
      target: correction.target as CorrectionTarget,
      confidence: correction.confidence,
      status: 'approved',
      createdAt: correction.created_at,
      updatedAt: correction.updated_at,
    });

    target = determined.target;
    targetId = determined.targetId;
    targetSection = determined.targetSection;
    confidence = determined.confidence;
  }

  // Update the correction with routing info
  db.updateCorrection(input.correctionId, {
    target,
    target_id: targetId || null,
    target_section: targetSection || null,
  });

  // Determine next step based on target
  let nextStep: string;
  switch (target) {
    case 'skill':
      nextStep = targetId
        ? `Edit skill file: .claude/skills/${targetId}/SKILL.md`
        : 'Create or update skill file with this pattern';
      break;
    case 'agent':
      nextStep = `Store as agent_improvement memory for @agent-${targetId || determineAgent({
        id: correction.id,
        projectId: correction.project_id,
        agentId: correction.agent_id || undefined,
        originalContent: correction.original_content,
        correctedContent: correction.corrected_content,
        rawUserMessage: correction.raw_user_message,
        matchedPatterns: [],
        target,
        confidence,
        status: 'approved',
        createdAt: correction.created_at,
        updatedAt: correction.updated_at,
      })}`;
      break;
    case 'memory':
      nextStep = 'Store as lesson or decision in Memory Copilot';
      break;
    case 'preference':
      nextStep = 'Store as user preference in Memory Copilot';
      break;
  }

  return {
    correctionId: input.correctionId,
    target,
    targetId: targetId || 'auto-detect',
    targetSection,
    confidence,
    status: 'approved',
    nextStep,
  };
}

/**
 * Apply a routed correction to its target
 */
export async function correctionApply(
  db: DatabaseClient,
  correctionId: string,
  sessionId: string
): Promise<CorrectionApplicationResult> {
  // Get the correction
  const correction = db.getCorrection(correctionId);
  if (!correction) {
    return {
      correctionId,
      success: false,
      error: 'Correction not found',
    };
  }

  if (correction.status !== 'approved') {
    return {
      correctionId,
      success: false,
      error: `Cannot apply correction with status: ${correction.status}`,
    };
  }

  const target = correction.target as CorrectionTarget;

  try {
    switch (target) {
      case 'agent': {
        // Store as agent_improvement memory
        const agentId = correction.target_id || correction.agent_id || determineAgent({
          id: correction.id,
          projectId: correction.project_id,
          agentId: correction.agent_id || undefined,
          originalContent: correction.original_content,
          correctedContent: correction.corrected_content,
          rawUserMessage: correction.raw_user_message,
          matchedPatterns: [],
          target,
          confidence: correction.confidence,
          status: 'approved',
          createdAt: correction.created_at,
          updatedAt: correction.updated_at,
        });

        const memoryId = uuidv4();
        db.insertMemory({
          id: memoryId,
          content: correction.corrected_content,
          type: 'agent_improvement' as MemoryType,
          tags: JSON.stringify(['correction', `agent:${agentId}`]),
          metadata: JSON.stringify({
            agentId,
            targetSection: correction.target_section || 'Core Behaviors',
            currentContent: correction.original_content,
            suggestedContent: correction.corrected_content,
            rationale: `Auto-captured from user correction: ${correction.raw_user_message.substring(0, 100)}`,
            status: 'pending',
            correctionId: correction.id,
          }),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          session_id: sessionId,
        });

        // Mark correction as applied
        db.updateCorrection(correctionId, {
          status: 'applied',
          applied_at: new Date().toISOString(),
        });

        return {
          correctionId,
          success: true,
          modifiedResource: {
            type: 'agent',
            id: agentId,
            section: correction.target_section || undefined,
          },
        };
      }

      case 'memory': {
        // Store as lesson
        const memoryId = uuidv4();
        db.insertMemory({
          id: memoryId,
          content: correction.corrected_content,
          type: 'lesson' as MemoryType,
          tags: JSON.stringify(['correction', 'learned']),
          metadata: JSON.stringify({
            source: 'correction',
            correctionId: correction.id,
            originalContext: correction.original_content,
          }),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          session_id: sessionId,
        });

        // Mark correction as applied
        db.updateCorrection(correctionId, {
          status: 'applied',
          applied_at: new Date().toISOString(),
        });

        return {
          correctionId,
          success: true,
          modifiedResource: {
            type: 'memory',
            id: memoryId,
          },
        };
      }

      case 'preference': {
        // Store as decision (preferences are decisions about style)
        const memoryId = uuidv4();
        db.insertMemory({
          id: memoryId,
          content: `User preference: ${correction.corrected_content}`,
          type: 'decision' as MemoryType,
          tags: JSON.stringify(['preference', 'style']),
          metadata: JSON.stringify({
            source: 'correction',
            correctionId: correction.id,
            previousApproach: correction.original_content,
          }),
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          session_id: sessionId,
        });

        // Mark correction as applied
        db.updateCorrection(correctionId, {
          status: 'applied',
          applied_at: new Date().toISOString(),
        });

        return {
          correctionId,
          success: true,
          modifiedResource: {
            type: 'preference',
            id: memoryId,
          },
        };
      }

      case 'skill': {
        // For skills, we can't directly modify files - return instructions
        // Mark as applied anyway (user will manually update skill file)
        db.updateCorrection(correctionId, {
          status: 'applied',
          applied_at: new Date().toISOString(),
        });

        const skillId = correction.target_id || 'unknown';
        return {
          correctionId,
          success: true,
          modifiedResource: {
            type: 'skill',
            id: skillId,
            diff: `Add to skill file:\n\n${correction.corrected_content}`,
          },
        };
      }

      default:
        return {
          correctionId,
          success: false,
          error: `Unknown target type: ${target}`,
        };
    }
  } catch (error) {
    return {
      correctionId,
      success: false,
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

/**
 * Batch route multiple corrections
 */
export function correctionRouteBatch(
  db: DatabaseClient,
  correctionIds: string[],
  sessionId: string
): CorrectionRouteOutput[] {
  return correctionIds.map((id) => {
    try {
      return correctionRoute(db, { correctionId: id }, sessionId);
    } catch (error) {
      return {
        correctionId: id,
        target: 'memory' as CorrectionTarget,
        targetId: '',
        confidence: 0,
        status: 'approved' as const,
        nextStep: `Error: ${error instanceof Error ? error.message : 'Unknown error'}`,
      };
    }
  });
}

/**
 * Batch apply multiple corrections
 */
export async function correctionApplyBatch(
  db: DatabaseClient,
  correctionIds: string[],
  sessionId: string
): Promise<CorrectionApplicationResult[]> {
  const results: CorrectionApplicationResult[] = [];

  for (const id of correctionIds) {
    const result = await correctionApply(db, id, sessionId);
    results.push(result);
  }

  return results;
}
