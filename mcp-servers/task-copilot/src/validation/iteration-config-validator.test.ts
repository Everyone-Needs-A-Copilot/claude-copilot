/**
 * Tests for Iteration Configuration Validator
 */

import assert from 'assert';
import {
  IterationConfigValidator,
  getIterationConfigValidator,
  validateIterationConfig,
  validateIterationConfigOrThrow,
  validateCompletionPromises,
  validateCommandRule,
  validateContentPatternRule,
  validateCoverageRule,
  validateFileExistenceRule,
  validateCustomRule,
  type IterationConfigInput,
} from './iteration-config-validator.js';

describe('IterationConfigValidator', () => {
  let validator: IterationConfigValidator;

  beforeEach(() => {
    validator = new IterationConfigValidator();
  });

  describe('Basic Configuration Validation', () => {
    it('validates a minimal valid configuration', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
      expect(result.config).toBeDefined();
      expect(result.config?.maxIterations).toBe(10);
    });

    it('validates a complete configuration with all optional fields', () => {
      const input: IterationConfigInput = {
        maxIterations: 15,
        completionPromises: [
          '<promise>COMPLETE</promise>',
          '<promise>BLOCKED</promise>',
        ],
        validationRules: [
          {
            type: 'command',
            name: 'tests_pass',
            config: {
              command: 'npm test',
              expectedExitCode: 0,
              timeout: 120000,
            },
          },
        ],
        circuitBreakerThreshold: 3,
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
      expect(result.errors).toHaveLength(0);
    });

    it('rejects configuration with missing required fields', () => {
      const input = {
        maxIterations: 10,
        // Missing completionPromises
      } as unknown as IterationConfigInput;

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
      expect(result.errors.length).toBeGreaterThan(0);
      expect(result.errors[0].message).toContain('completionPromises');
    });
  });

  describe('maxIterations Validation', () => {
    it('accepts valid maxIterations values', () => {
      const validValues = [1, 10, 50, 100];

      validValues.forEach((value) => {
        const input: IterationConfigInput = {
          maxIterations: value,
          completionPromises: ['<promise>COMPLETE</promise>'],
        };
        const result = validator.validateConfig(input);
        expect(result.valid).toBe(true);
      });
    });

    it('rejects maxIterations below minimum', () => {
      const input: IterationConfigInput = {
        maxIterations: 0,
        completionPromises: ['<promise>COMPLETE</promise>'],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
      expect(result.errors.some((e) => e.field.includes('maxIterations'))).toBe(true);
    });

    it('rejects maxIterations above maximum', () => {
      const input: IterationConfigInput = {
        maxIterations: 101,
        completionPromises: ['<promise>COMPLETE</promise>'],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
      expect(result.errors.some((e) => e.field.includes('maxIterations'))).toBe(true);
    });

    it('rejects non-integer maxIterations', () => {
      const input = {
        maxIterations: 10.5,
        completionPromises: ['<promise>COMPLETE</promise>'],
      } as IterationConfigInput;

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });
  });

  describe('completionPromises Validation', () => {
    it('accepts valid completion promises', () => {
      const validPromises = [
        ['<promise>COMPLETE</promise>'],
        ['<promise>BLOCKED</promise>'],
        ['<promise>COMPLETE</promise>', '<promise>BLOCKED</promise>'],
        ['<promise>ESCALATE</promise>'],
      ];

      validPromises.forEach((promises) => {
        const input: IterationConfigInput = {
          maxIterations: 10,
          completionPromises: promises,
        };
        const result = validator.validateConfig(input);
        expect(result.valid).toBe(true);
      });
    });

    it('rejects empty completionPromises array', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: [],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
      expect(result.errors.some((e) => e.message.includes('at least'))).toBe(true);
    });

    it('rejects invalid promise format', () => {
      const invalidPromises = [
        'COMPLETE', // Missing tags
        '<promise>complete</promise>', // Lowercase
        '<PROMISE>COMPLETE</PROMISE>', // Wrong tag case
        '<promise>COMPLETE', // Incomplete tag
        'promise>COMPLETE</promise>', // Missing opening <
      ];

      invalidPromises.forEach((promise) => {
        const input: IterationConfigInput = {
          maxIterations: 10,
          completionPromises: [promise],
        };
        const result = validator.validateConfig(input);
        expect(result.valid).toBe(false);
      });
    });

    it('rejects duplicate promises', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: [
          '<promise>COMPLETE</promise>',
          '<promise>COMPLETE</promise>',
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
      expect(result.errors.some((e) => e.message.includes('unique'))).toBe(true);
    });
  });

  describe('circuitBreakerThreshold Validation', () => {
    it('uses default value when not specified', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
      // Default value should be applied by the system, not the schema
    });

    it('accepts valid threshold values', () => {
      const validValues = [1, 3, 10, 20];

      validValues.forEach((value) => {
        const input: IterationConfigInput = {
          maxIterations: 10,
          completionPromises: ['<promise>COMPLETE</promise>'],
          circuitBreakerThreshold: value,
        };
        const result = validator.validateConfig(input);
        expect(result.valid).toBe(true);
      });
    });

    it('rejects threshold below minimum', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        circuitBreakerThreshold: 0,
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });

    it('rejects threshold above maximum', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        circuitBreakerThreshold: 21,
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });
  });

  describe('Command Rule Validation', () => {
    it('validates command rule with all fields', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'command',
            name: 'tests_pass',
            config: {
              command: 'npm test',
              expectedExitCode: 0,
              timeout: 120000,
              workingDirectory: '/path/to/dir',
              env: { NODE_ENV: 'test' },
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
    });

    it('validates command rule with successExitCodes', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'command',
            name: 'tests_pass',
            config: {
              command: 'npm test',
              successExitCodes: [0, 1],
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
    });

    it('rejects command rule without command', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'command',
            name: 'tests_pass',
            config: {
              timeout: 120000,
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });
  });

  describe('Content Pattern Rule Validation', () => {
    it('validates content pattern rule with all fields', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'content_pattern',
            name: 'promise_complete',
            config: {
              pattern: '<promise>COMPLETE</promise>',
              target: 'agent_output',
              flags: 'i',
              mustMatch: true,
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
    });

    it('validates all valid target values', () => {
      const validTargets = ['agent_output', 'task_notes', 'work_product_latest'];

      validTargets.forEach((target) => {
        const input: IterationConfigInput = {
          maxIterations: 10,
          completionPromises: ['<promise>COMPLETE</promise>'],
          validationRules: [
            {
              type: 'content_pattern',
              name: 'test',
              config: {
                pattern: 'test',
                target,
              },
            },
          ],
        };
        const result = validator.validateConfig(input);
        expect(result.valid).toBe(true);
      });
    });

    it('rejects invalid target value', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'content_pattern',
            name: 'test',
            config: {
              pattern: 'test',
              target: 'invalid_target',
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });

    it('rejects content pattern rule without pattern', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'content_pattern',
            name: 'test',
            config: {
              target: 'agent_output',
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });
  });

  describe('Coverage Rule Validation', () => {
    it('validates coverage rule with all fields', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'coverage',
            name: 'coverage_threshold',
            config: {
              minCoverage: 80,
              format: 'lcov',
              reportPath: 'coverage/lcov.info',
              scope: 'lines',
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
    });

    it('validates all valid format values', () => {
      const validFormats = ['lcov', 'json', 'cobertura'];

      validFormats.forEach((format) => {
        const input: IterationConfigInput = {
          maxIterations: 10,
          completionPromises: ['<promise>COMPLETE</promise>'],
          validationRules: [
            {
              type: 'coverage',
              name: 'test',
              config: {
                minCoverage: 80,
                format,
              },
            },
          ],
        };
        const result = validator.validateConfig(input);
        expect(result.valid).toBe(true);
      });
    });

    it('validates all valid scope values', () => {
      const validScopes = ['lines', 'branches', 'functions', 'statements'];

      validScopes.forEach((scope) => {
        const input: IterationConfigInput = {
          maxIterations: 10,
          completionPromises: ['<promise>COMPLETE</promise>'],
          validationRules: [
            {
              type: 'coverage',
              name: 'test',
              config: {
                minCoverage: 80,
                format: 'lcov',
                scope,
              },
            },
          ],
        };
        const result = validator.validateConfig(input);
        expect(result.valid).toBe(true);
      });
    });

    it('rejects minCoverage below 0', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'coverage',
            name: 'test',
            config: {
              minCoverage: -1,
              format: 'lcov',
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });

    it('rejects minCoverage above 100', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'coverage',
              name: 'test',
            config: {
              minCoverage: 101,
              format: 'lcov',
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });
  });

  describe('File Existence Rule Validation', () => {
    it('validates file existence rule', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'file_existence',
            name: 'files_created',
            config: {
              paths: ['src/index.ts', 'src/types.ts'],
              allMustExist: true,
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
    });

    it('rejects empty paths array', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'file_existence',
            name: 'test',
            config: {
              paths: [],
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });
  });

  describe('Custom Rule Validation', () => {
    it('validates custom rule', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'custom',
            name: 'custom_validator',
            config: {
              validatorId: 'my-custom-validator',
              customParam: 'value',
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(true);
    });

    it('rejects custom rule without validatorId', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'custom',
            name: 'test',
            config: {
              customParam: 'value',
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });

    it('rejects invalid validatorId format', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
        validationRules: [
          {
            type: 'custom',
            name: 'test',
            config: {
              validatorId: 'invalid id with spaces!',
            },
          },
        ],
      };

      const result = validator.validateConfig(input);

      expect(result.valid).toBe(false);
    });
  });

  describe('Convenience Functions', () => {
    it('validateIterationConfigOrThrow returns config on success', () => {
      const input: IterationConfigInput = {
        maxIterations: 10,
        completionPromises: ['<promise>COMPLETE</promise>'],
      };

      const config = validateIterationConfigOrThrow(input);

      expect(config).toBeDefined();
      expect(config.maxIterations).toBe(10);
    });

    it('validateIterationConfigOrThrow throws on error', () => {
      const input = {
        maxIterations: 0,
        completionPromises: [],
      } as IterationConfigInput;

      expect(() => validateIterationConfigOrThrow(input)).toThrow();
    });
  });

  describe('Singleton Instance', () => {
    it('getIterationConfigValidator returns same instance', () => {
      const instance1 = getIterationConfigValidator();
      const instance2 = getIterationConfigValidator();

      expect(instance1).toBe(instance2);
    });
  });
});
