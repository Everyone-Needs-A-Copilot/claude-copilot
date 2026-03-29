/**
 * SkillsSh Provider
 *
 * Fetches public skills from the skills.sh API (free, no auth required)
 */

import type { SkillMeta, SkillMatch, SkillsShSearchResponse, ProviderResult } from '../types.js';

const SKILLSSH_API = 'https://skills.sh/api';

export class SkillsShProvider {
  /**
   * Search for skills by query
   */
  async searchSkills(query: string, limit = 10): Promise<ProviderResult<SkillMatch[]>> {
    try {
      const response = await fetch(
        `${SKILLSSH_API}/search?q=${encodeURIComponent(query)}&limit=${limit}`
      );

      if (!response.ok) {
        return {
          success: false,
          error: `skills.sh API error: ${response.status}`,
          source: 'skills.sh'
        };
      }

      const data = await response.json() as SkillsShSearchResponse;

      const matches: SkillMatch[] = data.skills
        .slice(0, limit)
        .map((skill, index) => ({
          id: skill.id,
          name: skill.skillId,
          description: skill.name,
          author: skill.source.split('/')[0],
          keywords: this.extractKeywords(skill.name),
          source: 'skills.sh' as const,
          stars: skill.installs,  // installs mapped to stars field
          relevance: 1 - (index * 0.1),  // Simple relevance based on position
          githubUrl: `https://github.com/${skill.source}/tree/main/${skill.skillId}`
        }));

      return {
        success: true,
        data: matches,
        source: 'skills.sh'
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
        source: 'skills.sh'
      };
    }
  }

  /**
   * Fetch full skill content from GitHub
   */
  async getSkillContent(githubUrl: string): Promise<ProviderResult<string>> {
    try {
      // Convert GitHub URL to raw content URL
      // https://github.com/user/repo/tree/main/path/to/skill
      // -> https://raw.githubusercontent.com/user/repo/main/path/to/skill/SKILL.md
      const rawBase = githubUrl
        .replace('github.com', 'raw.githubusercontent.com')
        .replace('/tree/', '/');

      const skillMdUrl = `${rawBase}/SKILL.md`;

      const response = await fetch(skillMdUrl);

      // Fallback: try master branch if main 404s
      if (response.status === 404 && githubUrl.includes('/tree/main/')) {
        const masterUrl = githubUrl.replace('/tree/main/', '/tree/master/');
        const masterRawBase = masterUrl
          .replace('github.com', 'raw.githubusercontent.com')
          .replace('/tree/', '/');
        const masterSkillMdUrl = `${masterRawBase}/SKILL.md`;

        const masterResponse = await fetch(masterSkillMdUrl);
        if (!masterResponse.ok) {
          return {
            success: false,
            error: `Failed to fetch skill content: ${masterResponse.status}`,
            source: 'skills.sh'
          };
        }
        const content = await masterResponse.text();
        return {
          success: true,
          data: content,
          source: 'skills.sh'
        };
      }

      if (!response.ok) {
        return {
          success: false,
          error: `Failed to fetch skill content: ${response.status}`,
          source: 'skills.sh'
        };
      }

      const content = await response.text();

      return {
        success: true,
        data: content,
        source: 'skills.sh'
      };
    } catch (error) {
      return {
        success: false,
        error: error instanceof Error ? error.message : 'Unknown error',
        source: 'skills.sh'
      };
    }
  }

  /**
   * Search and fetch full skill by name
   */
  async getSkillByName(name: string): Promise<ProviderResult<{ meta: SkillMeta; content: string }>> {
    // Search for the skill
    const searchResult = await this.searchSkills(name, 10);

    if (!searchResult.success || !searchResult.data?.length) {
      return {
        success: false,
        error: `Skill not found in skills.sh: ${name}`,
        source: 'skills.sh'
      };
    }

    // Find exact match or closest match
    const match = searchResult.data.find(s =>
      s.name.toLowerCase() === name.toLowerCase()
    ) || searchResult.data[0];

    if (!match.githubUrl) {
      return {
        success: false,
        error: `No GitHub URL available for skill: ${name}`,
        source: 'skills.sh'
      };
    }

    // Fetch content from GitHub
    const contentResult = await this.getSkillContent(match.githubUrl);

    if (!contentResult.success || !contentResult.data) {
      return {
        success: false,
        error: contentResult.error || 'Failed to fetch skill content from GitHub',
        source: 'skills.sh'
      };
    }

    return {
      success: true,
      data: {
        meta: {
          id: match.id,
          name: match.name,
          description: match.description,
          author: match.author,
          keywords: match.keywords,
          source: 'skills.sh',
          stars: match.stars
        },
        content: contentResult.data
      },
      source: 'skills.sh'
    };
  }

  /**
   * Extract keywords from skill name (split on hyphens/underscores)
   */
  private extractKeywords(name: string): string[] {
    return name
      .toLowerCase()
      .split(/[-_\s]+/)
      .filter(word => word.length > 2)
      .slice(0, 10);
  }
}
