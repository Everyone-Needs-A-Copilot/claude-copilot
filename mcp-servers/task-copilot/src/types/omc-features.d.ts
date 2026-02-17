/**
 * OMC Features Types - Shared TypeScript types for OMC learnings integration
 *
 * This module provides type definitions for 5 OMC-inspired features:
 * 1. Ecomode: Model routing based on task complexity
 * 2. Keyword modifiers: Magic keywords for model selection and task actions
 * 3. HUD: Heads-up display for real-time status
 * 4. Skill extraction: Pattern-based skill detection from work products
 * 5. Install orchestration: Dependency checking and platform detection
 *
 * @see PRD-omc-learnings (OMC Learnings Integration)
 */
/**
 * Complexity score for a task (0.0 = trivial, 1.0 = highly complex)
 *
 * Scoring factors:
 * - Keyword patterns ("bug fix" → low, "architecture" → high)
 * - File count (single file → low, 10+ files → high)
 * - Agent type (@agent-qa → low, @agent-ta → medium)
 */
export interface ComplexityScore {
    /** Overall complexity score (0.0 to 1.0) */
    score: number;
    /** Breakdown of contributing factors */
    factors: {
        /** Score from keyword analysis (0.0 to 1.0) */
        keywords: number;
        /** Score from file count analysis (0.0 to 1.0) */
        fileCount: number;
        /** Score from agent type (0.0 to 1.0) */
        agentType: number;
    };
    /** Human-readable complexity level */
    level: 'trivial' | 'low' | 'medium' | 'high' | 'very_high';
    /** Explanation of score calculation */
    reasoning: string;
}
/**
 * Model routing decision based on complexity
 */
export interface ModelRoute {
    /** Model to use (haiku, sonnet, opus) */
    model: 'haiku' | 'sonnet' | 'opus';
    /** Confidence in routing decision (0.0 to 1.0) */
    confidence: number;
    /** Reason for model selection */
    reason: string;
    /** Whether this is an override (user specified model explicitly) */
    isOverride: boolean;
    /** Estimated cost tier (low, medium, high) */
    costTier: 'low' | 'medium' | 'high';
}
/**
 * Cost tracking for model usage
 */
export interface CostTracking {
    /** Model used */
    model: 'haiku' | 'sonnet' | 'opus';
    /** Input tokens consumed */
    inputTokens: number;
    /** Output tokens generated */
    outputTokens: number;
    /** Estimated cost in USD */
    estimatedCost: number;
    /** Timestamp of usage */
    timestamp: string;
    /** Task ID if applicable */
    taskId?: string;
}
/**
 * Modifier keywords for model selection
 *
 * Examples: eco:, opus:, fast:, sonnet:, haiku:, auto:, ralph:
 */
export interface ModifierKeyword {
    /** The keyword matched (without colon) */
    keyword: 'eco' | 'opus' | 'fast' | 'sonnet' | 'haiku' | 'auto' | 'ralph';
    /** Position in message (0-based character index) */
    position: number;
    /** Full matched text (including colon) */
    raw: string;
    /** Model to route to (null for auto/eco) */
    targetModel: 'haiku' | 'sonnet' | 'opus' | null;
}
/**
 * Action keywords for task type
 *
 * Examples: fix:, add:, refactor:, optimize:
 */
export interface ActionKeyword {
    /** The keyword matched (without colon) */
    keyword: 'fix' | 'add' | 'refactor' | 'optimize' | 'test' | 'doc' | 'deploy';
    /** Position in message (0-based character index) */
    position: number;
    /** Full matched text (including colon) */
    raw: string;
    /** Suggested agent routing */
    suggestedAgent?: string;
}
/**
 * Parsed command with extracted keywords
 */
export interface ParsedCommand {
    /** Original message text */
    originalMessage: string;
    /** Message with keywords stripped */
    cleanMessage: string;
    /** Modifier keyword found (max 1) */
    modifier: ModifierKeyword | null;
    /** Action keyword found (max 1) */
    action: ActionKeyword | null;
    /** Validation errors if invalid combination */
    errors: string[];
    /** Whether parsing succeeded */
    valid: boolean;
}
/**
 * Status line state for real-time progress display
 */
export interface StatuslineState {
    /** Current task ID */
    taskId: string;
    /** Task title (truncated) */
    taskTitle: string;
    /** Current status */
    status: 'pending' | 'in_progress' | 'blocked' | 'completed';
    /** Progress percentage (0-100) */
    progressPercent: number;
    /** Current agent working */
    agentId?: string;
    /** Stream ID if parallel work */
    streamId?: string;
    /** Optional token budget for stream/task */
    tokenBudget?: number;
    /** Files being modified */
    activeFiles: string[];
    /** Timestamp of last update */
    lastUpdate: string;
}
/**
 * Progress event for real-time updates
 */
export interface ProgressEvent {
    /** Event type */
    type: 'task_started' | 'task_updated' | 'task_completed' | 'file_modified' | 'agent_switched';
    /** Task ID */
    taskId: string;
    /** Event timestamp */
    timestamp: string;
    /** Event-specific payload */
    payload: Record<string, unknown>;
    /** Stream ID if applicable */
    streamId?: string;
}
/**
 * Keyboard shortcut configuration
 */
export interface KeyboardShortcut {
    /** Shortcut key combination (e.g., "Ctrl+P") */
    keys: string;
    /** Command to execute */
    command: string;
    /** Description for help text */
    description: string;
    /** Whether shortcut is enabled */
    enabled: boolean;
}
/**
 * Pattern candidate detected from work products
 */
export interface PatternCandidate {
    /** Pattern type (file_pattern, keyword, workflow) */
    type: 'file_pattern' | 'keyword' | 'workflow' | 'code_snippet';
    /** Pattern content/value */
    value: string;
    /** Confidence score (0.0 to 1.0) */
    confidence: number;
    /** Source work product ID */
    sourceWorkProductId: string;
    /** Frequency count (how many times pattern appeared) */
    frequency: number;
    /** Context where pattern was found */
    context: string;
}
/**
 * Skill template extracted from patterns
 */
export interface SkillTemplate {
    /** Generated skill name */
    name: string;
    /** Skill description */
    description: string;
    /** Trigger patterns for auto-detection */
    triggers: {
        /** File patterns (glob format) */
        filePatterns: string[];
        /** Keyword patterns */
        keywords: string[];
    };
    /** Skill content (markdown format) */
    content: string;
    /** Confidence in extraction (0.0 to 1.0) */
    confidence: number;
    /** Source work products used for extraction */
    sources: string[];
    /** Suggested category */
    category: 'framework' | 'pattern' | 'workflow' | 'best_practice';
}
/**
 * Dependency check result
 */
export interface DependencyCheck {
    /** Dependency name */
    name: string;
    /** Required version (semver or "latest") */
    requiredVersion: string;
    /** Installed version (null if not installed) */
    installedVersion: string | null;
    /** Whether dependency is satisfied */
    satisfied: boolean;
    /** Installation command if missing */
    installCommand?: string;
    /** Check timestamp */
    checkedAt: string;
}
/**
 * Platform configuration
 */
export interface PlatformConfig {
    /** Detected platform (darwin, linux, win32) */
    platform: 'darwin' | 'linux' | 'win32' | 'unknown';
    /** CPU architecture */
    arch: string;
    /** Node.js version */
    nodeVersion: string;
    /** Package manager detected (npm, yarn, pnpm) */
    packageManager: 'npm' | 'yarn' | 'pnpm' | 'unknown';
    /** Shell detected (bash, zsh, fish, powershell) */
    shell: string;
    /** Home directory path */
    homeDir: string;
    /** Whether running in CI environment */
    isCI: boolean;
}
/**
 * Ecomode configuration
 */
export interface EcomodeConfig {
    /** Whether ecomode is enabled globally */
    enabled: boolean;
    /** Default model for low complexity tasks */
    defaultLowComplexity: 'haiku' | 'sonnet';
    /** Default model for medium complexity tasks */
    defaultMediumComplexity: 'sonnet' | 'opus';
    /** Default model for high complexity tasks */
    defaultHighComplexity: 'opus';
    /** Complexity thresholds (0.0 to 1.0) */
    thresholds: {
        /** Below this = low complexity */
        low: number;
        /** Below this = medium complexity */
        medium: number;
    };
    /** Whether to allow user overrides */
    allowOverrides: boolean;
}
/**
 * HUD configuration
 */
export interface HudConfig {
    /** Whether HUD is enabled */
    enabled: boolean;
    /** Refresh interval in milliseconds */
    refreshInterval: number;
    /** WebSocket port for real-time updates */
    websocketPort: number;
    /** Whether to show file changes */
    showFileChanges: boolean;
    /** Whether to show agent switches */
    showAgentSwitches: boolean;
    /** Keyboard shortcuts */
    shortcuts: KeyboardShortcut[];
}
/**
 * Skill extraction configuration
 */
export interface SkillExtractionConfig {
    /** Whether auto-extraction is enabled */
    enabled: boolean;
    /** Minimum confidence threshold (0.0 to 1.0) */
    minConfidence: number;
    /** Minimum pattern frequency to consider */
    minFrequency: number;
    /** Maximum skills to extract per session */
    maxSkillsPerSession: number;
    /** Whether to auto-save extracted skills */
    autoSave: boolean;
    /** Output directory for extracted skills */
    outputDir: string;
}
/**
 * Validates complexity score is within valid range
 */
export declare function isValidComplexityScore(score: number): boolean;
/**
 * Validates model name
 */
export declare function isValidModel(model: string): model is 'haiku' | 'sonnet' | 'opus';
/**
 * Validates modifier keyword
 */
export declare function isValidModifier(keyword: string): keyword is ModifierKeyword['keyword'];
/**
 * Validates action keyword
 */
export declare function isValidAction(keyword: string): keyword is ActionKeyword['keyword'];
//# sourceMappingURL=omc-features.d.ts.map
