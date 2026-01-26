/**
 * OMC (Orchestration and Monitoring Command) Feature Types
 *
 * Shared TypeScript types and configuration schemas for all 5 OMC features:
 * 1. Ecomode: Dynamic model routing and cost optimization
 * 2. Keyword system: Command parsing and intent detection
 * 3. HUD: Status line, progress tracking, and keyboard shortcuts
 * 4. Skill extraction: Pattern detection and template generation
 * 5. Install system: Dependency checks and platform configuration
 *
 * @see PRD-6df7cc11-c4d4-4f48-9e0c-1275cf6fb327 (OMC Features)
 */

// ============================================================================
// ECOMODE TYPES
// ============================================================================

/**
 * Model complexity classification
 */
export type ComplexityLevel = 'trivial' | 'simple' | 'moderate' | 'complex' | 'expert';

/**
 * Available Claude models for routing
 */
export type ClaudeModel =
  | 'claude-haiku-3-5-20241022'      // Fast, cheap
  | 'claude-sonnet-3-5-20241022'     // Balanced
  | 'claude-sonnet-4-5-20250929'     // Current flagship
  | 'claude-opus-4-5-20251101';      // Most capable

/**
 * Complexity score with reasoning
 */
export interface ComplexityScore {
  /** Computed complexity level */
  level: ComplexityLevel;

  /** Confidence in the classification (0-1) */
  confidence: number;

  /** Factors contributing to complexity */
  factors: {
    /** Number of files involved */
    fileCount: number;

    /** Lines of code to process */
    linesOfCode?: number;

    /** Number of dependencies/imports */
    dependencies?: number;

    /** Domain complexity (auth, payments, etc.) */
    domainComplexity?: 'low' | 'medium' | 'high';

    /** Architectural impact */
    architecturalImpact?: 'isolated' | 'component' | 'system' | 'critical';

    /** Whether task involves multiple agents */
    multiAgent?: boolean;
  };

  /** Reasoning for the classification */
  reasoning: string;

  /** Timestamp when scored */
  scoredAt: string;
}

/**
 * Model routing decision
 */
export interface ModelRoute {
  /** Selected model */
  model: ClaudeModel;

  /** Reason for selection */
  reason: string;

  /** Whether this was auto-selected or overridden */
  autoSelected: boolean;

  /** Cost multiplier relative to Haiku (1x = Haiku baseline) */
  costMultiplier: number;

  /** Estimated tokens for task */
  estimatedTokens?: number;
}

/**
 * Cost tracking for ecomode
 */
export interface CostTracking {
  /** Task ID */
  taskId: string;

  /** Model used */
  model: ClaudeModel;

  /** Input tokens consumed */
  inputTokens: number;

  /** Output tokens generated */
  outputTokens: number;

  /** Total cost in USD */
  totalCost: number;

  /** Cost breakdown */
  breakdown: {
    inputCost: number;
    outputCost: number;
  };

  /** Whether this was optimal model choice */
  wasOptimal: boolean;

  /** How much could have been saved (if not optimal) */
  potentialSavings?: number;

  /** Timestamp */
  timestamp: string;
}

/**
 * Ecomode configuration
 */
export interface EcomodeConfig {
  /** Whether ecomode is enabled */
  enabled: boolean;

  /** Default model if auto-routing disabled */
  defaultModel: ClaudeModel;

  /** Budget limit per task (USD) */
  budgetLimit?: number;

  /** Whether to allow model overrides */
  allowOverrides: boolean;

  /** Complexity thresholds for auto-routing */
  thresholds: {
    trivial: { maxFiles: number; maxLines: number; model: ClaudeModel };
    simple: { maxFiles: number; maxLines: number; model: ClaudeModel };
    moderate: { maxFiles: number; maxLines: number; model: ClaudeModel };
    complex: { maxFiles: number; maxLines: number; model: ClaudeModel };
    expert: { model: ClaudeModel };
  };
}

// ============================================================================
// KEYWORD SYSTEM TYPES
// ============================================================================

/**
 * Modifier keywords that affect command behavior
 */
export type ModifierKeyword =
  | '--technical'       // Force technical flow
  | '--defect'          // Force defect flow
  | '--experience'      // Force experience flow
  | '--skip-sd'         // Skip service design
  | '--skip-uxd'        // Skip UX design
  | '--skip-uids'       // Skip UI design
  | '--no-checkpoints'  // Disable checkpoints
  | '--verbose'         // Verbose output
  | '--minimal'         // Minimal output
  | '--ultrawork';      // Ultrawork activation mode

/**
 * Action keywords for intent detection
 */
export type ActionKeyword =
  | 'fix' | 'bug' | 'broken' | 'error' | 'crash'                    // Defect
  | 'build' | 'add' | 'create' | 'implement'                         // Experience
  | 'refactor' | 'optimize' | 'architecture' | 'performance'         // Technical
  | 'improve' | 'enhance' | 'update' | 'change';                     // Ambiguous

/**
 * Detected intent from command parsing
 */
export type CommandIntent = 'experience' | 'technical' | 'defect' | 'clarification';

/**
 * Parsed command with intent and modifiers
 */
export interface ParsedCommand {
  /** Original command text */
  rawCommand: string;

  /** Detected intent */
  intent: CommandIntent;

  /** Confidence in intent (0-1) */
  intentConfidence: number;

  /** Extracted modifiers */
  modifiers: ModifierKeyword[];

  /** Core task description (without modifiers) */
  taskDescription: string;

  /** Detected action keywords */
  actionKeywords: ActionKeyword[];

  /** Whether clarification is needed */
  needsClarification: boolean;

  /** Suggested agent chain */
  suggestedChain?: string[];

  /** Parsing timestamp */
  parsedAt: string;
}

/**
 * Keyword configuration
 */
export interface KeywordConfig {
  /** Custom action keywords to recognize */
  customActions?: Record<string, CommandIntent>;

  /** Whether to enable strict mode (exact matches only) */
  strictMode: boolean;

  /** Minimum confidence threshold for intent (0-1) */
  confidenceThreshold: number;

  /** Whether to auto-clarify ambiguous commands */
  autoClarify: boolean;
}

// ============================================================================
// HUD TYPES
// ============================================================================

/**
 * Status line display state
 */
export interface StatuslineState {
  /** Current task ID */
  taskId?: string;

  /** Task title (truncated for display) */
  taskTitle?: string;

  /** Task status */
  taskStatus?: 'pending' | 'in_progress' | 'completed' | 'blocked';

  /** Current agent executing */
  currentAgent?: string;

  /** Progress percentage (0-100) */
  progress?: number;

  /** Active stream (if in orchestration) */
  activeStream?: string;

  /** Total streams in orchestration */
  totalStreams?: number;

  /** Token usage (current / budget) */
  tokenUsage?: {
    current: number;
    budget: number;
    percentage: number;
  };

  /** Ecomode active model */
  activeModel?: ClaudeModel;

  /** Current cost (USD) */
  currentCost?: number;

  /** Warnings or alerts */
  alerts?: Array<{
    level: 'info' | 'warn' | 'error';
    message: string;
  }>;

  /** Last updated timestamp */
  updatedAt: string;
}

/**
 * Progress event for HUD updates
 */
export interface ProgressEvent {
  /** Event type */
  type:
    | 'task_started'
    | 'task_progress'
    | 'task_completed'
    | 'agent_handoff'
    | 'checkpoint_created'
    | 'stream_spawned'
    | 'validation_failed'
    | 'cost_alert';

  /** Task ID */
  taskId: string;

  /** Event payload */
  payload: Record<string, unknown>;

  /** Timestamp */
  timestamp: string;
}

/**
 * Keyboard shortcut definition
 */
export interface KeyboardShortcut {
  /** Shortcut key combination (e.g., 'Ctrl+P') */
  key: string;

  /** Action to trigger */
  action: string;

  /** Description for help menu */
  description: string;

  /** Whether enabled */
  enabled: boolean;

  /** Scope (global or task-specific) */
  scope: 'global' | 'task';
}

/**
 * HUD configuration
 */
export interface HudConfig {
  /** Whether HUD is enabled */
  enabled: boolean;

  /** Update frequency in milliseconds */
  updateInterval: number;

  /** Whether to show token usage */
  showTokens: boolean;

  /** Whether to show cost tracking */
  showCost: boolean;

  /** Whether to show progress bars */
  showProgress: boolean;

  /** Custom keyboard shortcuts */
  shortcuts: KeyboardShortcut[];

  /** Theme settings */
  theme: {
    primaryColor: string;
    warningColor: string;
    errorColor: string;
    successColor: string;
  };
}

// ============================================================================
// SKILL EXTRACTION TYPES
// ============================================================================

/**
 * Detected pattern candidate for skill extraction
 */
export interface PatternCandidate {
  /** Unique ID for this pattern */
  id: string;

  /** Pattern type */
  type:
    | 'code_snippet'        // Reusable code block
    | 'workflow'            // Multi-step process
    | 'decision_tree'       // Conditional logic
    | 'template'            // File/project template
    | 'best_practice';      // Documented guideline

  /** Pattern name/title */
  name: string;

  /** Description of what pattern does */
  description: string;

  /** Pattern content/implementation */
  content: string;

  /** Source files where pattern was detected */
  sourceFiles: string[];

  /** Frequency of pattern usage */
  frequency: number;

  /** Confidence that this is a reusable pattern (0-1) */
  confidence: number;

  /** Tags/keywords for categorization */
  tags: string[];

  /** Whether pattern has been promoted to skill */
  promoted: boolean;

  /** Detection timestamp */
  detectedAt: string;
}

/**
 * Skill template for generation
 */
export interface SkillTemplate {
  /** Skill name */
  name: string;

  /** Skill description */
  description: string;

  /** Skill category */
  category: string;

  /** Skill content (Markdown) */
  content: string;

  /** Trigger files (glob patterns) */
  triggerFiles?: string[];

  /** Trigger keywords */
  triggerKeywords?: string[];

  /** Dependencies (other skills) */
  dependencies?: string[];

  /** Version */
  version: string;

  /** Author/source */
  author?: string;

  /** Generated timestamp */
  generatedAt: string;
}

/**
 * Skill extraction configuration
 */
export interface SkillExtractionConfig {
  /** Whether auto-extraction is enabled */
  enabled: boolean;

  /** Minimum frequency to consider pattern (count) */
  minFrequency: number;

  /** Minimum confidence threshold (0-1) */
  minConfidence: number;

  /** File patterns to scan */
  scanPatterns: string[];

  /** File patterns to ignore */
  ignorePatterns: string[];

  /** Whether to auto-promote high-confidence patterns */
  autoPromote: boolean;

  /** Auto-promotion confidence threshold (0-1) */
  autoPromoteThreshold: number;
}

// ============================================================================
// INSTALL SYSTEM TYPES
// ============================================================================

/**
 * Platform identifier
 */
export type Platform = 'darwin' | 'linux' | 'win32';

/**
 * Dependency check result
 */
export interface DependencyCheck {
  /** Dependency name */
  name: string;

  /** Whether dependency is installed */
  installed: boolean;

  /** Version detected (if installed) */
  version?: string;

  /** Required version or range */
  requiredVersion?: string;

  /** Whether version meets requirements */
  versionMatch?: boolean;

  /** Installation path (if found) */
  installPath?: string;

  /** Error message (if check failed) */
  error?: string;

  /** How to install (if missing) */
  installCommand?: string;

  /** Check timestamp */
  checkedAt: string;
}

/**
 * Platform-specific configuration
 */
export interface PlatformConfig {
  /** Platform identifier */
  platform: Platform;

  /** OS version */
  osVersion?: string;

  /** Required system dependencies */
  systemDependencies: Array<{
    name: string;
    version?: string;
    optional?: boolean;
  }>;

  /** Required Node.js version */
  nodeVersion?: string;

  /** Required npm packages */
  npmPackages?: Array<{
    name: string;
    version?: string;
    dev?: boolean;
  }>;

  /** Environment variables to set */
  envVars?: Record<string, string>;

  /** Pre-install scripts */
  preInstall?: string[];

  /** Post-install scripts */
  postInstall?: string[];

  /** Custom installation notes */
  notes?: string[];
}

/**
 * Installation progress tracking
 */
export interface InstallProgress {
  /** Installation ID */
  installId: string;

  /** Current phase */
  phase:
    | 'checking_dependencies'
    | 'installing_system'
    | 'installing_npm'
    | 'configuring_env'
    | 'running_scripts'
    | 'verifying'
    | 'completed'
    | 'failed';

  /** Progress percentage (0-100) */
  progress: number;

  /** Current step being executed */
  currentStep?: string;

  /** Steps completed */
  completedSteps: string[];

  /** Steps failed */
  failedSteps: Array<{
    step: string;
    error: string;
  }>;

  /** Start timestamp */
  startedAt: string;

  /** Completion timestamp */
  completedAt?: string;

  /** Total duration (ms) */
  duration?: number;
}

/**
 * Install system configuration
 */
export interface InstallConfig {
  /** Whether to auto-detect platform */
  autoDetectPlatform: boolean;

  /** Whether to auto-install missing dependencies */
  autoInstall: boolean;

  /** Whether to prompt before installing */
  promptBeforeInstall: boolean;

  /** Timeout for dependency checks (ms) */
  checkTimeout: number;

  /** Timeout for installations (ms) */
  installTimeout: number;

  /** Whether to verify after installation */
  verifyAfterInstall: boolean;

  /** Custom dependency overrides */
  customDependencies?: Record<string, DependencyCheck>;
}

// ============================================================================
// SHARED/COMPOSITE TYPES
// ============================================================================

/**
 * Combined OMC feature configuration
 */
export interface OmcConfig {
  ecomode: EcomodeConfig;
  keywords: KeywordConfig;
  hud: HudConfig;
  skillExtraction: SkillExtractionConfig;
  install: InstallConfig;
}

/**
 * OMC feature status
 */
export interface OmcStatus {
  /** Whether each feature is enabled */
  features: {
    ecomode: boolean;
    keywords: boolean;
    hud: boolean;
    skillExtraction: boolean;
    install: boolean;
  };

  /** Current active model (ecomode) */
  activeModel?: ClaudeModel;

  /** HUD state */
  hudState?: StatuslineState;

  /** Pending pattern candidates */
  pendingPatterns?: number;

  /** Installation health */
  installHealth?: {
    allDependenciesMet: boolean;
    missingDependencies: string[];
  };

  /** Last status check */
  lastChecked: string;
}

// ============================================================================
// VALIDATION SCHEMAS (for runtime validation)
// ============================================================================

/**
 * JSON Schema type definitions for configuration validation
 * These can be used with libraries like Ajv for runtime validation
 */
export const OmcSchemas = {
  ComplexityScore: {
    type: 'object',
    required: ['level', 'confidence', 'factors', 'reasoning', 'scoredAt'],
    properties: {
      level: { type: 'string', enum: ['trivial', 'simple', 'moderate', 'complex', 'expert'] },
      confidence: { type: 'number', minimum: 0, maximum: 1 },
      factors: { type: 'object' },
      reasoning: { type: 'string' },
      scoredAt: { type: 'string', format: 'date-time' },
    },
  },

  ModelRoute: {
    type: 'object',
    required: ['model', 'reason', 'autoSelected', 'costMultiplier'],
    properties: {
      model: {
        type: 'string',
        enum: [
          'claude-haiku-3-5-20241022',
          'claude-sonnet-3-5-20241022',
          'claude-sonnet-4-5-20250929',
          'claude-opus-4-5-20251101',
        ],
      },
      reason: { type: 'string' },
      autoSelected: { type: 'boolean' },
      costMultiplier: { type: 'number', minimum: 1 },
      estimatedTokens: { type: 'number', minimum: 0 },
    },
  },

  ParsedCommand: {
    type: 'object',
    required: ['rawCommand', 'intent', 'intentConfidence', 'modifiers', 'taskDescription', 'actionKeywords', 'needsClarification', 'parsedAt'],
    properties: {
      rawCommand: { type: 'string' },
      intent: { type: 'string', enum: ['experience', 'technical', 'defect', 'clarification'] },
      intentConfidence: { type: 'number', minimum: 0, maximum: 1 },
      modifiers: { type: 'array', items: { type: 'string' } },
      taskDescription: { type: 'string' },
      actionKeywords: { type: 'array', items: { type: 'string' } },
      needsClarification: { type: 'boolean' },
      suggestedChain: { type: 'array', items: { type: 'string' } },
      parsedAt: { type: 'string', format: 'date-time' },
    },
  },

  OmcConfig: {
    type: 'object',
    required: ['ecomode', 'keywords', 'hud', 'skillExtraction', 'install'],
    properties: {
      ecomode: { type: 'object' },
      keywords: { type: 'object' },
      hud: { type: 'object' },
      skillExtraction: { type: 'object' },
      install: { type: 'object' },
    },
  },
} as const;

// ============================================================================
// TYPE GUARDS
// ============================================================================

/**
 * Type guard for ComplexityLevel
 */
export function isComplexityLevel(value: unknown): value is ComplexityLevel {
  return typeof value === 'string' && ['trivial', 'simple', 'moderate', 'complex', 'expert'].includes(value);
}

/**
 * Type guard for ClaudeModel
 */
export function isClaudeModel(value: unknown): value is ClaudeModel {
  return typeof value === 'string' && [
    'claude-haiku-3-5-20241022',
    'claude-sonnet-3-5-20241022',
    'claude-sonnet-4-5-20250929',
    'claude-opus-4-5-20251101',
  ].includes(value);
}

/**
 * Type guard for CommandIntent
 */
export function isCommandIntent(value: unknown): value is CommandIntent {
  return typeof value === 'string' && ['experience', 'technical', 'defect', 'clarification'].includes(value);
}

/**
 * Type guard for Platform
 */
export function isPlatform(value: unknown): value is Platform {
  return typeof value === 'string' && ['darwin', 'linux', 'win32'].includes(value);
}
