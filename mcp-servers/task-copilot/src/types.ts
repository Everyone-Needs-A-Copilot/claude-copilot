/**
 * Type definitions for the Task Copilot MCP Server
 */

// Task and PRD status types
export type TaskStatus = 'pending' | 'in_progress' | 'blocked' | 'completed' | 'cancelled';
export type PrdStatus = 'active' | 'archived' | 'cancelled';
export type WorkProductType = 'technical_design' | 'implementation' | 'test_plan' | 'security_review' | 'documentation' | 'architecture' | 'specification' | 'other';

// Initiative (lightweight reference)
export interface Initiative {
  id: string;
  title: string;
  description?: string;
  createdAt: string;
  updatedAt: string;
}

// Milestone for PRD progress tracking
export interface Milestone {
  id: string;
  name: string;
  description?: string;
  taskIds: string[]; // Tasks that must be complete for milestone
}

// PRD Metadata structure
export interface PrdMetadata extends Record<string, unknown> {
  priority?: string;
  complexity?: string;
  tags?: string[];
  milestones?: Milestone[]; // Optional progress milestones
  scopeLocked?: boolean; // When true, only @agent-ta can create tasks for this PRD
  prdType?: 'FEATURE' | 'EXPERIENCE' | 'DEFECT' | 'QUESTION' | 'TECHNICAL'; // Auto-detected from title/description
}

// PRD
export interface Prd {
  id: string;
  initiativeId: string;
  title: string;
  description?: string;
  content: string;
  metadata: PrdMetadata;
  status: PrdStatus;
  createdAt: string;
  updatedAt: string;
}

// Task
export interface Task {
  id: string;
  prdId?: string;
  parentId?: string;
  title: string;
  description?: string;
  assignedAgent?: string;
  status: TaskStatus;
  blockedReason?: string;
  notes?: string;
  metadata: TaskMetadata;
  createdAt: string;
  updatedAt: string;
}

// Task Metadata with Stream Support
export interface TaskMetadata extends Record<string, unknown> {
  // Existing metadata fields
  complexity?: 'Low' | 'Medium' | 'High' | 'Very High';
  priority?: string;
  dependencies?: string[];
  acceptanceCriteria?: string[];
  phase?: string;

  // Activation mode (auto-detected from keywords or explicitly set)
  activationMode?: 'ultrawork' | 'analyze' | 'quick' | 'thorough' | null;

  // Stream metadata (Command Arguments & Independent Streams)
  streamId?: string;          // Auto-generated: "Stream-A", "Stream-B", etc.
  streamName?: string;         // Human-readable: "foundation", "auth-api", etc.
  streamPhase?: 'foundation' | 'parallel' | 'integration';
  files?: string[];            // File paths this task will touch
  streamDependencies?: string[]; // Other streamIds this depends on
  worktreePath?: string;       // Git worktree path for this stream
  branchName?: string;         // Git branch name for this stream

  // Quality gates (Quality Gates Configuration)
  qualityGates?: string[];    // Gate names to run before task completion

  // Verification enforcement (GSD-inspired DX improvements)
  verificationRequired?: boolean; // If true, requires acceptanceCriteria and proof to complete

  // Auto-commit on completion (git checkpoint system)
  autoCommit?: boolean;        // If true (default), auto-commit on task completion
  autoCommitOnComplete?: boolean; // If true, request auto-commit when task transitions to completed
  filesModified?: string[];    // File paths modified by this task (for staging)

  // Task isolation with git worktrees
  isolatedWorktree?: boolean;  // If true, task runs in isolated git worktree (opt-in)
  mergeConflicts?: string[];   // List of files with merge conflicts (set when merge fails)
  mergeConflictTimestamp?: string; // When merge conflict was detected

  // Preflight configuration (Session Boundary Protocol)
  preflight?: boolean;         // Whether to require preflight check (default: true for complex tasks)
  preflightConfig?: {
    checkDevServer?: boolean;  // Check if dev server is running
    devServerPort?: number;    // Port to check (default: 3000)
    testCommand?: string;      // Baseline test command to run
  };
}

// Work Product
export interface WorkProduct {
  id: string;
  taskId: string;
  type: WorkProductType;
  title: string;
  content: string;
  metadata: Record<string, unknown>;
  createdAt: string;
}

// Activity Log
export interface ActivityLog {
  id: string;
  initiativeId: string;
  type: string;
  entityId: string;
  summary: string;
  createdAt: string;
}

// Database row types (snake_case for SQLite)
export interface InitiativeRow {
  id: string;
  title: string;
  description: string | null;
  created_at: string;
  updated_at: string;
}

export interface PrdRow {
  id: string;
  initiative_id: string;
  title: string;
  description: string | null;
  content: string;
  metadata: string;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface TaskRow {
  id: string;
  prd_id: string | null;
  parent_id: string | null;
  title: string;
  description: string | null;
  assigned_agent: string | null;
  status: string;
  blocked_reason: string | null;
  notes: string | null;
  metadata: string;
  created_at: string;
  updated_at: string;
  archived: number;
  archived_at: string | null;
  archived_by_initiative_id: string | null;
}

export interface WorkProductRow {
  id: string;
  task_id: string;
  type: string;
  title: string;
  content: string;
  metadata: string;
  created_at: string;
  confidence: number | null;
}

export interface ActivityLogRow {
  id: string;
  initiative_id: string;
  type: string;
  entity_id: string;
  entity_type?: string | null;
  summary: string;
  metadata?: string | null;
  created_at: string;
}

// Tool input schemas
export interface PrdCreateInput {
  title: string;
  description?: string;
  content: string;
  metadata?: Record<string, unknown>;
}

export interface PrdGetInput {
  id: string;
  includeContent?: boolean;
}

export interface PrdListInput {
  initiativeId?: string;
  status?: PrdStatus;
}

export interface TaskCreateInput {
  title: string;
  description?: string;
  prdId?: string;
  parentId?: string;
  assignedAgent?: string;
  metadata?: TaskMetadata;
}

export interface TaskUpdateInput {
  id: string;
  status?: TaskStatus;
  assignedAgent?: string;
  notes?: string;
  blockedReason?: string;
  metadata?: TaskMetadata;
}

export interface TaskGetInput {
  id: string;
  includeSubtasks?: boolean;
  includeWorkProducts?: boolean;
}

export interface TaskListInput {
  prdId?: string;
  parentId?: string;
  status?: TaskStatus;
  assignedAgent?: string;
}

export interface WorkProductStoreInput {
  taskId: string;
  type: WorkProductType;
  title: string;
  content: string;
  metadata?: Record<string, unknown>;
  confidence?: number; // 0-1 scale, optional
}

export interface WorkProductGetInput {
  id: string;
}

export interface WorkProductListInput {
  taskId: string;
}

// Initiative integration tool inputs/outputs
export interface InitiativeLinkInput {
  initiativeId: string;
  title: string;
  description?: string;
}

export interface InitiativeLinkOutput {
  initiativeId: string;
  workspaceCreated: boolean;
  dbPath: string;
  archivedStreamsCount?: number;
}

export interface InitiativeArchiveInput {
  initiativeId?: string;
  archivePath?: string;
}

export interface InitiativeArchiveOutput {
  initiativeId: string;
  archivePath: string;
  prdCount: number;
  taskCount: number;
  workProductCount: number;
  archivedAt: string;
}

export interface InitiativeWipeInput {
  initiativeId?: string;
  confirm: boolean;
}

export interface InitiativeWipeOutput {
  initiativeId: string;
  deletedPrds: number;
  deletedTasks: number;
  deletedWorkProducts: number;
  deletedActivityLogs: number;
}

export interface ProgressSummaryInput {
  initiativeId?: string;
  minConfidence?: number; // Filter work products by minimum confidence (0-1)
}

export interface MilestoneProgress {
  id: string;
  name: string;
  description?: string;
  totalTasks: number;
  completedTasks: number;
  percentComplete: number;
  isComplete: boolean;
}

export interface VelocityTrend {
  period: '7d' | '14d' | '30d';
  tasksCompleted: number;
  tasksPerDay: number;
  trend: 'improving' | 'stable' | 'declining' | 'insufficient_data';
  trendIndicator: '↗' | '→' | '↘' | '?'; // Visual indicator for trend
}

export interface ProgressSummaryOutput {
  initiativeId: string;
  title: string;
  prds: {
    total: number;
    active: number;
    completed: number;
  };
  tasks: {
    total: number;
    pending: number;
    inProgress: number;
    completed: number;
    blocked: number;
    progressBar?: string; // ASCII progress bar
  };
  workProducts: {
    total: number;
    byType: Record<string, number>;
    confidenceStats?: {
      averageConfidence: number;
      highConfidence: number; // Count >= 0.8
      mediumConfidence: number; // Count 0.5-0.79
      lowConfidence: number; // Count < 0.5
      noConfidence: number; // Count with null confidence
    };
  };
  milestones?: MilestoneProgress[]; // Optional milestone progress
  velocity?: VelocityTrend[]; // Task completion velocity
  recentActivity: Array<{
    timestamp: string;
    type: string;
    summary: string;
  }>;
}

// ============================================================================
// AGENT PERFORMANCE TRACKING TYPES
// ============================================================================

export type PerformanceOutcome = 'success' | 'failure' | 'blocked' | 'reassigned';

export interface PerformanceRow {
  id: string;
  agent_id: string;
  task_id: string;
  work_product_type: string | null;
  complexity: string | null;
  outcome: string;
  duration_ms: number | null;
  created_at: string;
}

export interface AgentPerformanceGetInput {
  agentId?: string;
  workProductType?: string;
  complexity?: string;
  sinceDays?: number;
}

export interface AgentMetrics {
  total: number;
  success: number;
  failure: number;
  blocked: number;
  reassigned: number;
  successRate: number;
  completionRate: number;
}

export interface IterationMetrics {
  averageIterationsToCompletion: number;
  successRateByIterationCount: Record<number, number>;
  safetyGuardTriggers: {
    maxIterations: number;
    circuitBreaker: number;
    qualityRegression: number;
    thrashing: number;
  };
  iterationCompletionRate: number;
  totalIterationSessions: number;
  totalIterationsRun: number;
  averageDurationPerIteration: number | null;
}

export interface AgentPerformanceResult {
  agentId: string;
  metrics: AgentMetrics;
  byType: Record<string, { total: number; successRate: number }>;
  byComplexity: Record<string, { total: number; successRate: number }>;
  recentTrend: 'improving' | 'stable' | 'declining' | 'insufficient_data';
  iterationMetrics?: IterationMetrics;
}

export interface AgentPerformanceGetOutput {
  agents: AgentPerformanceResult[];
  summary: {
    totalRecords: number;
    periodStart: string | null;
    periodEnd: string | null;
  };
}

// ============================================================================
// CHECKPOINT TYPES
// ============================================================================

export type CheckpointTrigger = 'auto_status' | 'auto_subtask' | 'manual' | 'error' | 'auto_iteration' | 'auto_work_product';

// ============================================================================
// RALPH WIGGUM ITERATION TYPES
// ============================================================================

export type CompletionSignal = 'CONTINUE' | 'COMPLETE' | 'BLOCKED' | 'ESCALATE';

/**
 * Iteration configuration (simplified version for storage)
 * For full hook configuration types, see validation/iteration-hook-types.ts
 */
export interface IterationConfig {
  maxIterations: number;
  completionPromises: string[];
  validationRules?: Array<{
    type: string;
    name?: string;
    config: Record<string, unknown>;
  }>;
  circuitBreakerThreshold?: number;

  /**
   * Optional hook configuration
   * Stored as JSON in checkpoint.iteration_config
   */
  hooks?: {
    stopHooks?: Array<{
      name: string;
      validationRules: Array<{
        type: string;
        name: string;
        config: Record<string, unknown>;
      }>;
      action: 'complete' | 'blocked' | 'escalate';
      priority: number;
    }>;
    preIterationHooks?: Array<{
      name: string;
      actions: Array<{
        type: string;
        config: Record<string, unknown>;
      }>;
      trigger: string;
    }>;
    postIterationHooks?: Array<{
      name: string;
      actions: Array<{
        type: string;
        config: Record<string, unknown>;
      }>;
      trigger: string;
    }>;
    circuitBreakerHooks?: Array<{
      name: string;
      strategy: string;
      config: Record<string, unknown>;
      action: 'escalate' | 'blocked';
    }>;
  };
}

export interface IterationHistoryEntry {
  iteration: number;
  timestamp: string;
  validationResult: {
    passed: boolean;
    flags: Array<{
      ruleId: string;
      message: string;
      severity: string;
    }>;
  };
  checkpointId: string;
}

export interface ValidationState {
  lastRun: string;
  passed: boolean;
  results: Array<{
    ruleId: string;
    passed: boolean;
    message?: string;
  }>;
}

export interface CheckpointRow {
  id: string;
  task_id: string;
  sequence: number;
  trigger: string;
  task_status: string;
  task_notes: string | null;
  task_metadata: string;
  blocked_reason: string | null;
  assigned_agent: string | null;
  execution_phase: string | null;
  execution_step: number | null;
  agent_context: string | null;
  draft_content: string | null;
  draft_type: string | null;
  subtask_states: string;
  created_at: string;
  expires_at: string | null;
  // Ralph Wiggum Iteration Support (v4)
  iteration_config: string | null;
  iteration_number: number;
  iteration_history: string;
  completion_promises: string;
  validation_state: string | null;
}

export interface CheckpointCreateInput {
  taskId: string;
  trigger?: CheckpointTrigger;
  executionPhase?: string;
  executionStep?: number;
  agentContext?: Record<string, unknown>;
  draftContent?: string;
  draftType?: WorkProductType;
  expiresIn?: number; // Minutes until expiry
  // Ralph Wiggum iteration support
  iterationConfig?: IterationConfig;
  iterationNumber?: number;
  // Pause/Resume metadata (optional)
  pauseMetadata?: {
    pauseReason?: string;
    pausedBy?: 'user' | 'system';
    nextSteps?: string;
    blockers?: string[];
    keyFiles?: string[];
    estimatedResumeTime?: string;
  };
}

export interface CheckpointCreateOutput {
  id: string;
  taskId: string;
  sequence: number;
  trigger: CheckpointTrigger;
  createdAt: string;
  expiresAt: string | null;
}

export interface CheckpointResumeInput {
  taskId: string;
  checkpointId?: string;
}

export interface CheckpointResumeOutput {
  taskId: string;
  taskTitle: string;
  checkpointId: string;
  checkpointCreatedAt: string;
  restoredStatus: TaskStatus;
  restoredPhase: string | null;
  restoredStep: number | null;
  agentContext: Record<string, unknown> | null;
  hasDraft: boolean;
  draftType: WorkProductType | null;
  draftPreview: string | null;
  subtaskSummary: {
    total: number;
    completed: number;
    pending: number;
    blocked: number;
  };
  resumeInstructions: string;
  // Ralph Wiggum iteration state
  iterationConfig: IterationConfig | null;
  iterationNumber: number;
  iterationHistory: IterationHistoryEntry[];
  completionPromises: string[];
  validationState: ValidationState | null;
  // Pause metadata (if checkpoint was created via /pause)
  pauseMetadata?: {
    pauseReason?: string;
    pausedBy?: 'user' | 'system';
    nextSteps?: string;
    blockers?: string[];
    keyFiles?: string[];
    estimatedResumeTime?: string;
  };
}

export interface CheckpointGetInput {
  id: string;
}

export interface CheckpointGetOutput {
  id: string;
  taskId: string;
  taskTitle: string;
  sequence: number;
  trigger: CheckpointTrigger;
  taskStatus: TaskStatus;
  taskNotes: string | null;
  taskMetadata: Record<string, unknown>;
  blockedReason: string | null;
  assignedAgent: string | null;
  executionPhase: string | null;
  executionStep: number | null;
  agentContext: Record<string, unknown> | null;
  draftContent: string | null;
  draftType: WorkProductType | null;
  subtaskStates: Array<{ id: string; status: string }>;
  createdAt: string;
  expiresAt: string | null;
}

export interface CheckpointListInput {
  taskId: string;
  limit?: number;
  iterationNumber?: number;
  hasIteration?: boolean;
}

export interface CheckpointListOutput {
  taskId: string;
  checkpoints: Array<{
    id: string;
    sequence: number;
    trigger: CheckpointTrigger;
    phase: string | null;
    step: number | null;
    hasDraft: boolean;
    createdAt: string;
    expiresAt: string | null;
  }>;
}

export interface CheckpointCleanupInput {
  taskId?: string;
  olderThan?: number; // Minutes
  keepLatest?: number;
}

export interface CheckpointCleanupOutput {
  deletedCount: number;
  remainingCount: number;
}

// ============================================================================
// VALIDATION TYPES (core types, detailed rules in validation module)
// ============================================================================

export type ValidationSeverity = 'warn' | 'reject';

export interface ValidationFlag {
  ruleId: string;
  ruleName: string;
  severity: ValidationSeverity;
  message: string;
  suggestion?: string;
}

export interface ValidationResult {
  valid: boolean;
  flags: ValidationFlag[];
  rejected: boolean;
  actionableFeedback?: string;
}

export interface ValidationConfigGetOutput {
  version: string;
  defaultMode: 'warn' | 'reject' | 'skip';
  globalRulesCount: number;
  typeRules: Record<string, number>;
}

export interface ValidationRulesListInput {
  type?: WorkProductType;
}

export interface ValidationRulesListOutput {
  type: WorkProductType | 'global';
  rules: Array<{
    id: string;
    name: string;
    description: string;
    type: 'size' | 'structure' | 'completeness';
    severity: ValidationSeverity;
    enabled: boolean;
  }>;
}

// ============================================================================
// SESSION GUARD TYPES
// ============================================================================

export interface SessionGuardInput {
  action: 'check' | 'report';
  context?: {
    filesRead?: number;
    codeWritten?: boolean;
    agentUsed?: string;
    responseTokens?: number;
  };
}

export interface SessionGuardOutput {
  allowed: boolean;
  violations: string[];
  warnings: string[];
  suggestions: string[];
}

// ============================================================================
// AGENT HANDOFF TYPES
// ============================================================================

export interface AgentHandoffInput {
  taskId: string;
  fromAgent: string;
  toAgent: string;
  workProductId: string;
  handoffContext: string;
  chainPosition: number;
  chainLength: number;
}

export interface AgentHandoffOutput {
  id: string;
  taskId: string;
  fromAgent: string;
  toAgent: string;
  chainPosition: number;
  chainLength: number;
  createdAt: string;
}

export interface AgentChainGetInput {
  taskId: string;
}

export interface HandoffRecord {
  id: string;
  fromAgent: string;
  toAgent: string;
  workProductId: string;
  handoffContext: string;
  chainPosition: number;
  chainLength: number;
  createdAt: string;
}

export interface AgentChainGetOutput {
  taskId: string;
  chainLength: number;
  handoffs: HandoffRecord[];
  workProducts: Array<{
    id: string;
    type: WorkProductType;
    title: string;
    agent: string;
  }>;
}

// ============================================================================
// STREAM TYPES (Command Arguments & Independent Streams)
// ============================================================================

export interface StreamListInput {
  initiativeId?: string;
  prdId?: string;
  includeArchived?: boolean;
}

export interface StreamInfo {
  streamId: string;
  streamName: string;
  streamPhase: 'foundation' | 'parallel' | 'integration';
  totalTasks: number;
  completedTasks: number;
  inProgressTasks: number;
  blockedTasks: number;
  pendingTasks: number;
  files: string[];
  dependencies: string[];
  // Git worktree isolation
  worktreePath?: string;
  branchName?: string;
}

export interface StreamListOutput {
  streams: StreamInfo[];
}

export interface StreamGetInput {
  streamId: string;
  initiativeId?: string;
  includeArchived?: boolean;
}

export interface StreamGetOutput {
  streamId: string;
  streamName: string;
  streamPhase: 'foundation' | 'parallel' | 'integration';
  tasks: Task[];
  dependencies: string[];
  status: 'pending' | 'in_progress' | 'completed' | 'blocked';
  // Git worktree isolation
  worktreePath?: string;
  branchName?: string;
  // Archival metadata
  archived?: boolean;
  archivedAt?: string;
  archivedByInitiativeId?: string;
}

export interface StreamConflictCheckInput {
  files: string[];
  excludeStreamId?: string;
  initiativeId?: string;
}

export interface StreamConflictCheckOutput {
  hasConflict: boolean;
  conflicts: Array<{
    file: string;
    streamId: string;
    streamName: string;
    taskId: string;
    taskTitle: string;
    taskStatus: TaskStatus;
  }>;
}

export interface StreamUnarchiveInput {
  streamId: string;
  initiativeId?: string;
  prdId?: string; // Optional: only unarchive tasks belonging to this PRD
}

export interface StreamUnarchiveOutput {
  streamId: string;
  tasksUnarchived: number;
  newInitiativeId: string;
}

export interface StreamArchiveAllInput {
  confirm: boolean; // Safety flag - must be true to proceed
  initiativeId?: string; // Optional: only archive streams from specific initiative
  prdId?: string; // Optional: only archive streams from specific PRD
}

export interface StreamArchiveAllOutput {
  streamsArchived: number;
  tasksArchived: number;
  archivedAt: string;
}

// ============================================================================
// PREFLIGHT CHECK TYPES (Session Boundary Protocol)
// ============================================================================

export type PreflightCheckStatus = 'pass' | 'warn' | 'fail' | 'skip';

export interface PreflightCheckInput {
  taskId?: string;
  initiativeId?: string;
  checkDevServer?: boolean;
  devServerPort?: number;
  testCommand?: string;
}

export interface PreflightResult {
  healthy: boolean;
  timestamp: string;
  checks: {
    progress: {
      status: PreflightCheckStatus;
      initiative?: string;
      tasksInProgress: number;
      blockedTasks: number;
      message?: string;
    };
    git: {
      status: PreflightCheckStatus;
      branch: string;
      clean: boolean;
      uncommittedFiles: number;
      message?: string;
    };
    devServer?: {
      status: PreflightCheckStatus;
      port?: number;
      message?: string;
    };
    tests?: {
      status: PreflightCheckStatus;
      passed?: number;
      failed?: number;
      message?: string;
    };
  };
  recommendations: string[];
}

// ============================================================================
// SCOPE CHANGE REQUEST TYPES (P3.3)
// ============================================================================

export type ScopeChangeRequestType = 'add_task' | 'modify_task' | 'remove_task';
export type ScopeChangeRequestStatus = 'pending' | 'approved' | 'rejected';

export interface ScopeChangeRequest {
  id: string;
  prdId: string;
  requestType: ScopeChangeRequestType;
  description: string;
  rationale: string;
  requestedBy: string;
  status: ScopeChangeRequestStatus;
  createdAt: string;
  reviewedAt?: string;
  reviewedBy?: string;
  reviewNotes?: string;
}

export interface ScopeChangeRequestRow {
  id: string;
  prd_id: string;
  request_type: string;
  description: string;
  rationale: string;
  requested_by: string;
  status: string;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  review_notes: string | null;
}

export interface ScopeChangeRequestInput {
  prdId: string;
  requestType: ScopeChangeRequestType;
  description: string;
  rationale: string;
  requestedBy: string;
}

export interface ScopeChangeReviewInput {
  id: string;
  status: 'approved' | 'rejected';
  reviewNotes?: string;
  reviewedBy?: string;
}

export interface ScopeChangeListInput {
  prdId?: string;
  status?: ScopeChangeRequestStatus;
}

// ============================================================================
// AGENT ACTIVITY TYPES
// ============================================================================

export interface AgentActivityRow {
  id: string;
  stream_id: string;
  agent_id: string;
  task_id: string;
  activity_description: string | null;
  phase: string | null;
  started_at: string;
  last_heartbeat: string;
  completed_at: string | null;
}

export interface AgentActivity {
  streamId: string;
  streamName: string;
  agentId: string;
  agentName: string;
  taskId: string;
  taskTitle: string;
  activityDescription?: string;
  phase?: string;
  startedAt: string;
  lastHeartbeat: string;
  isActive: boolean;
}

export interface AgentActivityListInput {
  streamId?: string;
  activeOnly?: boolean;
}

export interface AgentActivityListOutput {
  activities: AgentActivity[];
  totalActive: number;
  totalIdle: number;
}

// ============================================================================
// PROTOCOL VIOLATION TYPES
// ============================================================================

export type ViolationType =
  | 'files_read_exceeded'
  | 'code_written_directly'
  | 'plan_created_directly'
  | 'generic_agent_used'
  | 'response_tokens_exceeded'
  | 'work_product_not_stored';

export type ViolationSeverity = 'low' | 'medium' | 'high' | 'critical';

export interface ProtocolViolationRow {
  id: string;
  session_id: string;
  initiative_id: string | null;
  violation_type: ViolationType;
  severity: ViolationSeverity;
  context: string; // JSON
  suggestion: string | null;
  created_at: string;
}
