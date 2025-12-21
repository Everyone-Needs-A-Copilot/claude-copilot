/**
 * Local File Provider
 *
 * Fallback for git-synced skills stored in the repository
 */

import { readFileSync, existsSync, readdirSync, statSync } from 'fs';
import { join, basename } from 'path';
import type { Skill, SkillMeta, ProviderResult } from '../types.js';

export class LocalProvider {
  private skillsPath: string;
  private skillsCache: Map<string, SkillMeta> = new Map();

  constructor(skillsPath: string) {
    this.skillsPath = skillsPath;
    this.scanSkills();
  }

  /**
   * Scan local skills directory
   */
  private scanSkills(): void {
    if (!existsSync(this.skillsPath)) {
      return;
    }

    try {
      this.scanDirectory(this.skillsPath);
    } catch (error) {
      console.error('Error scanning local skills:', error);
    }
  }

  /**
   * Recursively scan directory for SKILL.md files
   */
  private scanDirectory(dir: string): void {
    const entries = readdirSync(dir);

    for (const entry of entries) {
      const fullPath = join(dir, entry);
      const stat = statSync(fullPath);

      if (stat.isDirectory()) {
        // Check for SKILL.md in this directory
        const skillPath = join(fullPath, 'SKILL.md');
        if (existsSync(skillPath)) {
          const meta = this.parseSkillMeta(skillPath);
          if (meta) {
            this.skillsCache.set(meta.name, meta);
          }
        }
        // Continue scanning subdirectories
        this.scanDirectory(fullPath);
      }
    }
  }

  /**
   * Parse skill metadata from SKILL.md
   */
  private parseSkillMeta(skillPath: string): SkillMeta | null {
    try {
      const content = readFileSync(skillPath, 'utf-8');

      // Parse YAML frontmatter
      const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
      if (!frontmatterMatch) {
        return null;
      }

      const frontmatter = frontmatterMatch[1];
      // Support both 'name:' and 'skill_name:' formats
      const nameMatch = frontmatter.match(/(?:skill_)?name:\s*(.+)/);
      const descMatch = frontmatter.match(/description:\s*(.+)/);

      if (!nameMatch) {
        return null;
      }

      const name = nameMatch[1].trim();
      const description = descMatch ? descMatch[1].trim() : '';

      // Extract category from path
      const pathParts = skillPath.split('/');
      const categoryIndex = pathParts.indexOf('01-skills');
      const category = categoryIndex >= 0 && pathParts.length > categoryIndex + 1
        ? pathParts[categoryIndex + 1].replace(/^\d+-/, '')
        : undefined;

      return {
        id: `local-${name}`,
        name,
        description,
        category,
        keywords: this.extractKeywords(description),
        source: 'local'
      };
    } catch (error) {
      console.error(`Error parsing skill at ${skillPath}:`, error);
      return null;
    }
  }

  /**
   * Extract keywords from description
   */
  private extractKeywords(description: string): string[] {
    const stopWords = new Set([
      'a', 'an', 'the', 'and', 'or', 'but', 'is', 'are', 'for', 'to', 'with',
      'use', 'when', 'you', 'your', 'of', 'in', 'on', 'at', 'by', 'this'
    ]);

    return description
      .toLowerCase()
      .replace(/[^\w\s]/g, ' ')
      .split(/\s+/)
      .filter(word => word.length > 2 && !stopWords.has(word))
      .slice(0, 10);
  }

  /**
   * Get skill by name
   */
  getSkill(name: string): ProviderResult<Skill> {
    const meta = this.skillsCache.get(name);
    if (!meta) {
      return { success: false, error: 'Skill not found', source: 'local' };
    }

    // Find the skill file
    const skillPath = this.findSkillPath(name);
    if (!skillPath) {
      return { success: false, error: 'Skill file not found', source: 'local' };
    }

    try {
      const content = readFileSync(skillPath, 'utf-8');
      return {
        success: true,
        data: {
          id: meta.id,
          name: meta.name,
          description: meta.description,
          content,
          category: meta.category,
          keywords: meta.keywords,
          source: 'local',
          version: '1.0.0',
          isProprietary: false
        },
        source: 'local'
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Read error',
        source: 'local'
      };
    }
  }

  /**
   * Find skill path by name
   */
  private findSkillPath(name: string): string | null {
    const search = (dir: string): string | null => {
      if (!existsSync(dir)) return null;

      const entries = readdirSync(dir);
      for (const entry of entries) {
        const fullPath = join(dir, entry);
        const stat = statSync(fullPath);

        if (stat.isDirectory()) {
          const skillPath = join(fullPath, 'SKILL.md');
          if (existsSync(skillPath)) {
            const content = readFileSync(skillPath, 'utf-8');
            const nameMatch = content.match(/(?:skill_)?name:\s*(.+)/);
            if (nameMatch && nameMatch[1].trim() === name) {
              return skillPath;
            }
          }
          // Check subdirectories
          const found = search(fullPath);
          if (found) return found;
        }
      }
      return null;
    };

    return search(this.skillsPath);
  }

  /**
   * List all local skills
   */
  listSkills(): ProviderResult<SkillMeta[]> {
    return {
      success: true,
      data: Array.from(this.skillsCache.values()),
      source: 'local'
    };
  }

  /**
   * Search skills by query
   */
  searchSkills(query: string): ProviderResult<SkillMeta[]> {
    const queryLower = query.toLowerCase();
    const matches = Array.from(this.skillsCache.values())
      .filter(skill =>
        skill.name.toLowerCase().includes(queryLower) ||
        skill.description.toLowerCase().includes(queryLower) ||
        skill.keywords.some(k => k.includes(queryLower))
      );

    return {
      success: true,
      data: matches,
      source: 'local'
    };
  }

  /**
   * Refresh skill cache
   */
  refresh(): void {
    this.skillsCache.clear();
    this.scanSkills();
  }

  /**
   * Get skill count
   */
  getCount(): number {
    return this.skillsCache.size;
  }
}
