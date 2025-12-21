/**
 * Skills Hub Types
 */

export interface Skill {
  id: string;
  name: string;
  description: string;
  content: string;
  category?: string;
  keywords: string[];
  tags?: string[];
  author?: string;
  source: SkillSource;
  sourceUrl?: string;
  version: string;
  isProprietary: boolean;
  cachedAt?: Date;
  expiresAt?: Date;
}

export interface SkillMeta {
  id: string;
  name: string;
  description: string;
  category?: string;
  keywords: string[];
  author?: string;
  source: SkillSource;
  stars?: number;
}

export interface SkillMatch extends SkillMeta {
  relevance: number;
  githubUrl?: string;  // URL to fetch skill content (for SkillsMP skills)
}

export type SkillSource = 'private' | 'skillsmp' | 'local' | 'cache';

export interface SkillSearchParams {
  query: string;
  source?: SkillSource;
  limit?: number;
}

export interface SkillGetParams {
  name: string;
  forceRefresh?: boolean;
}

export interface SkillSaveParams {
  name: string;
  description: string;
  content: string;
  category?: string;
  keywords: string[];
  tags?: string[];
  isProprietary?: boolean;
}

export interface CachedSkill {
  name: string;
  content: string;
  source: SkillSource;
  cachedAt: number;
  expiresAt: number;
}

export interface SkillsHubConfig {
  skillsmpApiKey?: string;
  postgresUrl?: string;
  cachePath: string;
  cacheTtlDays: number;
  localSkillsPath?: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
}

export interface SkillsMPSearchResponse {
  success: boolean;
  data: {
    skills: SkillsMPSkill[];
  };
}

export interface SkillsMPSkill {
  id: string;
  name: string;
  author: string;
  description: string;
  githubUrl: string;
  skillUrl: string;
  stars: number;
  updatedAt: number;
}

export interface ProviderResult<T> {
  success: boolean;
  data?: T;
  error?: string;
  source: SkillSource;
}

// ============================================================================
// Knowledge Repository Extension Types
// ============================================================================

/**
 * Extension type determines how the extension modifies the base agent
 */
export type ExtensionType = 'override' | 'extension' | 'skills';

/**
 * Fallback behavior when required skills are unavailable
 */
export type FallbackBehavior = 'use_base' | 'use_base_with_warning' | 'fail';

/**
 * Extension declaration from knowledge-manifest.json
 */
export interface ExtensionDeclaration {
  agent: string;
  type: ExtensionType;
  file: string;
  description?: string;
  requiredSkills?: string[];
  fallbackBehavior?: FallbackBehavior;
}

/**
 * Skill declaration from knowledge-manifest.json
 */
export interface ManifestSkillDeclaration {
  name: string;
  path: string;
  description?: string;
  keywords?: string[];
}

/**
 * Knowledge repository manifest structure
 */
export interface KnowledgeManifest {
  version: string;
  name: string;
  description?: string;
  framework?: {
    name: string;
    minVersion?: string;
  };
  extensions?: ExtensionDeclaration[];
  skills?: {
    local?: ManifestSkillDeclaration[];
    remote?: Array<{
      name: string;
      source: string;
      description?: string;
      fallback?: string;
    }>;
  };
  glossary?: string;
  config?: {
    preferProprietarySkills?: boolean;
    strictMode?: boolean;
  };
}

/**
 * Resolved extension with loaded content
 */
export interface ResolvedExtension {
  agent: string;
  type: ExtensionType;
  content: string;
  description?: string;
  requiredSkills: string[];
  fallbackBehavior: FallbackBehavior;
}

/**
 * Extension listing item
 */
export interface ExtensionListItem {
  agent: string;
  type: ExtensionType;
  description?: string;
  requiredSkills?: string[];
  fallbackBehavior?: FallbackBehavior;
}

/**
 * Knowledge repo status result
 */
export interface KnowledgeRepoStatus {
  configured: boolean;
  path?: string;
  manifest?: {
    name: string;
    description?: string;
    extensions: number;
    skills: number;
  };
  error?: string;
}
