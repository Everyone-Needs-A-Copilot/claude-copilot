/**
 * Default validation rules for work products
 */

import type { ValidationConfig } from './types.js';

export const DEFAULT_VALIDATION_CONFIG: ValidationConfig = {
  version: '1.0',
  defaultMode: 'warn',

  globalRules: [
    {
      id: 'size-max-global',
      name: 'Maximum Content Size',
      description: 'Prevents excessively large outputs',
      type: 'size',
      severity: 'warn',
      enabled: true,
      maxCharacters: 50000, // ~12,500 tokens
      minCharacters: 100,   // Minimum viable content
    },
    {
      id: 'structure-has-heading',
      name: 'Has Title/Header',
      description: 'Content should have at least one heading',
      type: 'structure',
      severity: 'warn',
      enabled: true,
      requiredPatterns: ['^#\\s+\\w+'], // At least one # heading
    },
  ],

  typeRules: {
    architecture: [
      {
        id: 'arch-sections',
        name: 'Architecture Required Sections',
        description: 'Architecture docs need specific sections',
        type: 'structure',
        severity: 'warn',
        enabled: true,
        requiredSections: ['Overview', 'Components'],
      },
      {
        id: 'arch-size',
        name: 'Architecture Size Limit',
        description: 'Architecture docs should be focused',
        type: 'size',
        severity: 'warn',
        enabled: true,
        maxCharacters: 30000, // ~7,500 tokens
      },
    ],

    technical_design: [
      {
        id: 'td-size',
        name: 'Technical Design Size',
        description: 'Technical designs should be focused',
        type: 'size',
        severity: 'warn',
        enabled: true,
        maxCharacters: 25000,
      },
      {
        id: 'td-completeness',
        name: 'Technical Design Completeness',
        description: 'Should have multiple sections',
        type: 'completeness',
        severity: 'warn',
        enabled: true,
        minSections: 3,
      },
    ],

    implementation: [
      {
        id: 'impl-code-blocks',
        name: 'Implementation Has Code',
        description: 'Implementation should include code',
        type: 'completeness',
        severity: 'warn',
        enabled: true,
        minCodeBlocks: 1,
      },
      {
        id: 'impl-size',
        name: 'Implementation Size',
        description: 'Implementation notes should be concise',
        type: 'size',
        severity: 'warn',
        enabled: true,
        maxCharacters: 20000,
      },
    ],

    test_plan: [
      {
        id: 'test-tables',
        name: 'Test Plan Has Test Cases',
        description: 'Test plans should have tabular test cases',
        type: 'completeness',
        severity: 'warn',
        enabled: true,
        minTables: 1,
      },
      {
        id: 'test-sections',
        name: 'Test Plan Structure',
        description: 'Test plans need scope and test cases',
        type: 'structure',
        severity: 'warn',
        enabled: true,
        requiredSections: ['Scope', 'Test'],
      },
    ],

    security_review: [
      {
        id: 'sec-findings',
        name: 'Security Has Findings',
        description: 'Security reviews should document findings',
        type: 'structure',
        severity: 'warn',
        enabled: true,
        requiredSections: ['Finding', 'Summary'],
      },
      {
        id: 'sec-tables',
        name: 'Security Uses Tables',
        description: 'Findings should be in tabular format',
        type: 'completeness',
        severity: 'warn',
        enabled: true,
        minTables: 1,
      },
    ],

    documentation: [
      {
        id: 'doc-examples',
        name: 'Documentation Has Examples',
        description: 'Docs should include code examples',
        type: 'completeness',
        severity: 'warn',
        enabled: true,
        minCodeBlocks: 1,
      },
      {
        id: 'doc-size',
        name: 'Documentation Size',
        description: 'Keep docs focused and scannable',
        type: 'size',
        severity: 'warn',
        enabled: true,
        maxCharacters: 30000,
      },
    ],

    specification: [
      {
        id: 'spec-sections',
        name: 'Specification Required Sections',
        description: 'Specifications need PRD reference and acceptance criteria',
        type: 'structure',
        severity: 'warn',
        enabled: true,
        requiredSections: ['PRD Reference', 'Acceptance Criteria'],
      },
      {
        id: 'spec-size',
        name: 'Specification Size',
        description: 'Specifications should be focused and actionable',
        type: 'size',
        severity: 'warn',
        enabled: true,
        maxCharacters: 25000,
      },
      {
        id: 'spec-completeness',
        name: 'Specification Completeness',
        description: 'Should have multiple defined sections',
        type: 'completeness',
        severity: 'warn',
        enabled: true,
        minSections: 4,
      },
    ],

    other: [
      {
        id: 'other-size',
        name: 'Generic Size Limit',
        description: 'All outputs have reasonable size',
        type: 'size',
        severity: 'warn',
        enabled: true,
        maxCharacters: 25000,
      },
    ],
  },
};
