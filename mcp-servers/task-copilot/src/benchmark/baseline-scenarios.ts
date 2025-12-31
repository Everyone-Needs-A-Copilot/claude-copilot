/**
 * Baseline Measurements for BENCH-3
 *
 * Simulates token usage WITHOUT Claude Copilot framework
 * All content is loaded directly into main context (no agent delegation, no Task Copilot storage)
 */

import { createMeasurementTracker } from './index.js';

/**
 * SCENARIO 1: Feature Implementation (Baseline - No Framework)
 *
 * WITHOUT framework:
 * - User reads all relevant code files into context
 * - Plans implementation inline in main session
 * - Writes all code in main session
 * - No agent delegation, no Task Copilot storage
 */
export function baselineScenario1_FeatureImplementation() {
  const tracker = createMeasurementTracker(
    'BASELINE-1',
    'Feature Implementation (No Framework)',
    { variant: 'baseline', framework: 'none' }
  );

  // User's initial request
  const mainInput = 'Add user authentication with JWT tokens to the Express.js API';
  tracker.measure('main_input', mainInput);

  // WITHOUT framework: User must read all relevant files into context
  const filesReadIntoContext = `
    // File: src/models/user.ts (150 lines)
    export interface User {
      id: string;
      email: string;
      passwordHash: string;
      createdAt: Date;
      updatedAt: Date;
    }

    export class UserModel {
      async findByEmail(email: string): Promise<User | null> { /* ... */ }
      async create(data: CreateUserDto): Promise<User> { /* ... */ }
      async updatePassword(id: string, hash: string): Promise<void> { /* ... */ }
    }
    // ... 120 more lines of user model code

    // File: src/routes/api.ts (200 lines)
    import express from 'express';
    export const apiRouter = express.Router();
    apiRouter.get('/users', async (req, res) => { /* ... */ });
    apiRouter.post('/users', async (req, res) => { /* ... */ });
    // ... 180 more lines of existing routes

    // File: src/middleware/validation.ts (100 lines)
    export const validateRequest = (schema: Schema) => { /* ... */ };
    export const validateEmail = (email: string) => { /* ... */ };
    // ... 80 more lines of validation code

    // File: src/config/database.ts (80 lines)
    export const dbConfig = { /* ... */ };
    export async function connectDatabase() { /* ... */ }
    // ... 60 more lines of DB config

    // File: package.json (50 lines)
    {
      "dependencies": {
        "express": "^4.18.0",
        "pg": "^8.10.0",
        // ... other dependencies
      }
    }

    // File: src/types/index.ts (120 lines)
    export interface ApiResponse<T> { /* ... */ }
    export interface ErrorResponse { /* ... */ }
    // ... 100 more lines of type definitions
  `.trim();

  // WITHOUT framework: Planning happens inline in main context
  const planningInMainContext = `
    ## Authentication Implementation Plan

    ### 1. Dependencies to Add
    - jsonwebtoken for JWT creation/verification
    - bcrypt for password hashing
    - express-validator for input validation

    ### 2. New Files to Create
    - src/middleware/auth.ts - JWT verification middleware
    - src/services/auth.service.ts - Authentication business logic
    - src/routes/auth.routes.ts - Login/logout endpoints
    - src/utils/jwt.ts - JWT utility functions

    ### 3. Existing Files to Modify
    - src/models/user.ts - Add password methods
    - src/routes/api.ts - Register auth routes
    - src/types/index.ts - Add auth types

    ### 4. Implementation Steps
    a) Install dependencies
    b) Create JWT utility functions
    c) Implement password hashing in user model
    d) Create authentication service
    e) Create auth middleware
    f) Add login/logout routes
    g) Protect existing routes with auth middleware

    ### 5. Testing Strategy
    - Unit tests for JWT utils
    - Unit tests for auth service
    - Integration tests for login flow
    - Integration tests for protected routes

    ### 6. Security Considerations
    - Use secure JWT signing algorithm (RS256)
    - Set appropriate token expiration
    - Implement refresh token mechanism
    - Hash passwords with bcrypt (cost factor 12)
    - Validate all inputs
    - Rate limit login attempts
  `.trim();

  // WITHOUT framework: All implementation code written in main context
  const implementationInMainContext = `
    // src/utils/jwt.ts
    import jwt from 'jsonwebtoken';

    const JWT_SECRET = process.env.JWT_SECRET || 'your-secret-key';
    const JWT_EXPIRES_IN = '1h';

    export function generateToken(userId: string): string {
      return jwt.sign({ userId }, JWT_SECRET, { expiresIn: JWT_EXPIRES_IN });
    }

    export function verifyToken(token: string): { userId: string } | null {
      try {
        const decoded = jwt.verify(token, JWT_SECRET) as { userId: string };
        return decoded;
      } catch (error) {
        return null;
      }
    }

    // src/services/auth.service.ts
    import bcrypt from 'bcrypt';
    import { UserModel } from '../models/user.js';
    import { generateToken } from '../utils/jwt.js';

    const SALT_ROUNDS = 12;

    export class AuthService {
      private userModel: UserModel;

      constructor() {
        this.userModel = new UserModel();
      }

      async register(email: string, password: string) {
        const existingUser = await this.userModel.findByEmail(email);
        if (existingUser) {
          throw new Error('User already exists');
        }

        const passwordHash = await bcrypt.hash(password, SALT_ROUNDS);
        const user = await this.userModel.create({ email, passwordHash });
        const token = generateToken(user.id);

        return { user, token };
      }

      async login(email: string, password: string) {
        const user = await this.userModel.findByEmail(email);
        if (!user) {
          throw new Error('Invalid credentials');
        }

        const isValid = await bcrypt.compare(password, user.passwordHash);
        if (!isValid) {
          throw new Error('Invalid credentials');
        }

        const token = generateToken(user.id);
        return { user, token };
      }
    }

    // src/middleware/auth.ts
    import { Request, Response, NextFunction } from 'express';
    import { verifyToken } from '../utils/jwt.js';

    export interface AuthRequest extends Request {
      userId?: string;
    }

    export async function authMiddleware(
      req: AuthRequest,
      res: Response,
      next: NextFunction
    ) {
      const authHeader = req.headers.authorization;
      if (!authHeader || !authHeader.startsWith('Bearer ')) {
        return res.status(401).json({ error: 'Unauthorized' });
      }

      const token = authHeader.substring(7);
      const decoded = verifyToken(token);

      if (!decoded) {
        return res.status(401).json({ error: 'Invalid token' });
      }

      req.userId = decoded.userId;
      next();
    }

    // src/routes/auth.routes.ts
    import express from 'express';
    import { AuthService } from '../services/auth.service.js';
    import { validateRequest } from '../middleware/validation.js';

    export const authRouter = express.Router();
    const authService = new AuthService();

    authRouter.post('/register', async (req, res) => {
      try {
        const { email, password } = req.body;
        const result = await authService.register(email, password);
        res.json(result);
      } catch (error) {
        res.status(400).json({ error: error.message });
      }
    });

    authRouter.post('/login', async (req, res) => {
      try {
        const { email, password } = req.body;
        const result = await authService.login(email, password);
        res.json(result);
      } catch (error) {
        res.status(401).json({ error: error.message });
      }
    });

    // src/routes/api.ts (modifications)
    import { authRouter } from './auth.routes.js';
    import { authMiddleware } from '../middleware/auth.js';

    // Register auth routes
    apiRouter.use('/auth', authRouter);

    // Protect existing routes
    apiRouter.use(authMiddleware);

    // ... existing routes now protected
  `.trim();

  // WITHOUT framework: All tests written in main context
  const testsInMainContext = `
    // tests/utils/jwt.test.ts
    import { generateToken, verifyToken } from '../../src/utils/jwt';

    describe('JWT Utils', () => {
      it('should generate valid token', () => {
        const token = generateToken('user-123');
        expect(token).toBeTruthy();
      });

      it('should verify valid token', () => {
        const token = generateToken('user-123');
        const decoded = verifyToken(token);
        expect(decoded?.userId).toBe('user-123');
      });

      it('should reject invalid token', () => {
        const decoded = verifyToken('invalid-token');
        expect(decoded).toBeNull();
      });
    });

    // tests/services/auth.service.test.ts
    import { AuthService } from '../../src/services/auth.service';

    describe('AuthService', () => {
      let authService: AuthService;

      beforeEach(() => {
        authService = new AuthService();
      });

      it('should register new user', async () => {
        const result = await authService.register('test@example.com', 'password123');
        expect(result.user).toBeDefined();
        expect(result.token).toBeDefined();
      });

      it('should login existing user', async () => {
        await authService.register('test@example.com', 'password123');
        const result = await authService.login('test@example.com', 'password123');
        expect(result.token).toBeDefined();
      });

      it('should reject invalid credentials', async () => {
        await authService.register('test@example.com', 'password123');
        await expect(
          authService.login('test@example.com', 'wrong-password')
        ).rejects.toThrow('Invalid credentials');
      });
    });

    // tests/integration/auth.test.ts
    import request from 'supertest';
    import { app } from '../../src/app';

    describe('Auth Integration', () => {
      it('should register and login', async () => {
        const registerRes = await request(app)
          .post('/api/auth/register')
          .send({ email: 'test@example.com', password: 'password123' });

        expect(registerRes.status).toBe(200);
        expect(registerRes.body.token).toBeDefined();

        const loginRes = await request(app)
          .post('/api/auth/login')
          .send({ email: 'test@example.com', password: 'password123' });

        expect(loginRes.status).toBe(200);
        expect(loginRes.body.token).toBeDefined();
      });

      it('should protect routes', async () => {
        const res = await request(app).get('/api/users');
        expect(res.status).toBe(401);
      });

      it('should allow access with valid token', async () => {
        const authRes = await request(app)
          .post('/api/auth/login')
          .send({ email: 'test@example.com', password: 'password123' });

        const token = authRes.body.token;

        const res = await request(app)
          .get('/api/users')
          .set('Authorization', \`Bearer \${token}\`);

        expect(res.status).toBe(200);
      });
    });
  `.trim();

  // WITHOUT framework: Documentation written in main context
  const documentationInMainContext = `
    # Authentication Implementation

    ## Overview
    Added JWT-based authentication to the Express.js API.

    ## New Dependencies
    - jsonwebtoken@9.0.0 - JWT generation and verification
    - bcrypt@5.1.0 - Password hashing

    ## API Endpoints

    ### POST /api/auth/register
    Register a new user account.

    **Request:**
    \`\`\`json
    {
      "email": "user@example.com",
      "password": "secure-password"
    }
    \`\`\`

    **Response:**
    \`\`\`json
    {
      "user": { "id": "...", "email": "..." },
      "token": "eyJhbGc..."
    }
    \`\`\`

    ### POST /api/auth/login
    Login with existing credentials.

    **Request:** Same as register
    **Response:** Same as register

    ## Protected Routes
    All routes under /api/* (except /api/auth/*) now require authentication.

    Add Authorization header: \`Bearer <token>\`

    ## Security Features
    - Passwords hashed with bcrypt (cost factor 12)
    - JWT tokens expire after 1 hour
    - Tokens signed with RS256 algorithm
    - Input validation on all auth endpoints

    ## Testing
    - 15 unit tests covering auth service and JWT utils
    - 8 integration tests covering full auth flow
    - All tests passing
  `.trim();

  // Total context in main session WITHOUT framework
  const totalMainContext = `
    ${mainInput}

    ${filesReadIntoContext}

    ${planningInMainContext}

    ${implementationInMainContext}

    ${testsInMainContext}

    ${documentationInMainContext}
  `.trim();

  tracker.measure('main_context', totalMainContext);

  // In baseline scenario (no framework):
  // - agent_output = 0 (no agent delegation)
  // - main_return = all content stays in main context
  // - storage = 0 (no Task Copilot)
  // - retrieval = 0 (no Task Copilot)

  tracker.measure('agent_output', ''); // No agent used
  tracker.measure('main_return', totalMainContext); // Everything in main
  tracker.measure('storage', ''); // No Task Copilot
  tracker.measure('retrieval', ''); // No Task Copilot

  return tracker;
}

/**
 * SCENARIO 2: Bug Investigation (Baseline - No Framework)
 *
 * WITHOUT framework:
 * - User reads error logs, stack traces, and all potentially related code
 * - Analyzes everything inline in main context
 * - No agent to investigate, all debugging in main session
 */
export function baselineScenario2_BugInvestigation() {
  const tracker = createMeasurementTracker(
    'BASELINE-2',
    'Bug Investigation (No Framework)',
    { variant: 'baseline', framework: 'none' }
  );

  const mainInput = 'Users reporting 500 errors on checkout - need to investigate';
  tracker.measure('main_input', mainInput);

  // WITHOUT framework: Load error logs directly into context
  const errorLogsInContext = `
    [2025-12-31 10:23:45] ERROR: Unhandled rejection in checkout handler
    Error: Cannot read property 'amount' of undefined
      at CheckoutService.processPayment (src/services/checkout.service.ts:45:32)
      at async CheckoutController.checkout (src/controllers/checkout.controller.ts:23:18)
      at async Router.handle (node_modules/express/lib/router/index.js:635:13)

    [2025-12-31 10:24:12] ERROR: Payment processing failed
    Error: Invalid payment method
      at PaymentGateway.charge (src/integrations/payment-gateway.ts:78:15)
      at CheckoutService.processPayment (src/services/checkout.service.ts:52:28)

    [2025-12-31 10:25:33] ERROR: Database connection timeout
    Error: Connection timeout after 30000ms
      at Pool.query (src/config/database.ts:112:11)
      at OrderRepository.create (src/repositories/order.repository.ts:34:22)

    [... 50 more error log entries similar to above ...]
  `.trim();

  // WITHOUT framework: Read all potentially related code files
  const codeFilesInContext = `
    // src/services/checkout.service.ts (180 lines)
    export class CheckoutService {
      async processPayment(cartId: string, paymentMethod: PaymentMethod) {
        const cart = await this.cartRepository.findById(cartId);
        const order = await this.createOrder(cart);

        // Line 45 - where error occurs
        const amount = cart.items.reduce((sum, item) => sum + item.price * item.quantity, 0);

        const payment = await this.paymentGateway.charge({
          amount: amount,
          method: paymentMethod,
          orderId: order.id
        });

        return { order, payment };
      }

      // ... 150 more lines
    }

    // src/controllers/checkout.controller.ts (120 lines)
    export class CheckoutController {
      async checkout(req: Request, res: Response) {
        try {
          const { cartId, paymentMethod } = req.body;
          const result = await this.checkoutService.processPayment(cartId, paymentMethod);
          res.json(result);
        } catch (error) {
          console.error('Checkout error:', error);
          res.status(500).json({ error: 'Checkout failed' });
        }
      }

      // ... 100 more lines
    }

    // src/integrations/payment-gateway.ts (200 lines)
    export class PaymentGateway {
      async charge(request: ChargeRequest) {
        // Validation logic
        if (!this.isValidPaymentMethod(request.method)) {
          throw new Error('Invalid payment method');
        }

        // Payment processing logic
        const response = await this.client.post('/charges', request);
        return response.data;
      }

      // ... 180 more lines
    }

    // src/repositories/order.repository.ts (150 lines)
    export class OrderRepository {
      async create(orderData: CreateOrderDto) {
        const query = 'INSERT INTO orders ...';
        const result = await this.db.query(query, [orderData]);
        return result.rows[0];
      }

      // ... 130 more lines
    }

    // src/repositories/cart.repository.ts (140 lines)
    export class CartRepository {
      async findById(cartId: string) {
        const query = 'SELECT * FROM carts WHERE id = $1';
        const result = await this.db.query(query, [cartId]);
        return result.rows[0];
      }

      // ... 120 more lines
    }

    // src/models/cart.ts (100 lines)
    export interface Cart {
      id: string;
      userId: string;
      items: CartItem[];
      createdAt: Date;
    }

    export interface CartItem {
      productId: string;
      quantity: number;
      price: number;
    }

    // ... 80 more lines
  `.trim();

  // WITHOUT framework: Analysis done inline in main context
  const analysisInContext = `
    ## Bug Analysis

    ### Root Cause
    The error "Cannot read property 'amount' of undefined" occurs because:
    1. cart.items might be undefined or null
    2. The reduce function tries to access items without null check

    ### Error Patterns from Logs
    - 45 instances of "Cannot read property 'amount'"
    - 12 instances of "Invalid payment method"
    - 8 instances of "Database connection timeout"

    ### Affected Code Path
    CheckoutController.checkout()
      → CheckoutService.processPayment()
      → cart.items.reduce() ← ERROR HERE

    ### Why It's Happening
    1. Cart might be deleted/expired between adding items and checkout
    2. Database query returns null but code doesn't check
    3. Race condition when multiple requests process same cart

    ### Impact
    - Affects ~5% of checkout attempts
    - Started after deployment on 2025-12-30
    - Causing revenue loss and poor user experience

    ## Proposed Fix

    1. Add null/undefined checks for cart and cart.items
    2. Add validation before payment processing
    3. Improve error messages for debugging
    4. Add retry logic for transient failures
    5. Add monitoring/alerting for checkout errors
  `.trim();

  // WITHOUT framework: Fix written inline in main context
  const fixInContext = `
    // src/services/checkout.service.ts (updated)
    export class CheckoutService {
      async processPayment(cartId: string, paymentMethod: PaymentMethod) {
        // ADD: Null checks and validation
        const cart = await this.cartRepository.findById(cartId);

        if (!cart) {
          throw new Error(\`Cart not found: \${cartId}\`);
        }

        if (!cart.items || cart.items.length === 0) {
          throw new Error('Cart is empty');
        }

        const order = await this.createOrder(cart);

        // FIXED: Safe reduce with proper null handling
        const amount = cart.items.reduce((sum, item) => {
          return sum + (item.price || 0) * (item.quantity || 0);
        }, 0);

        if (amount <= 0) {
          throw new Error('Invalid cart total amount');
        }

        // ADD: Validate payment method before processing
        if (!this.isValidPaymentMethod(paymentMethod)) {
          throw new Error(\`Invalid payment method: \${paymentMethod}\`);
        }

        const payment = await this.paymentGateway.charge({
          amount: amount,
          method: paymentMethod,
          orderId: order.id
        });

        return { order, payment };
      }

      private isValidPaymentMethod(method: PaymentMethod): boolean {
        return ['credit_card', 'debit_card', 'paypal'].includes(method);
      }

      // ... rest of file
    }
  `.trim();

  const totalMainContext = `
    ${mainInput}
    ${errorLogsInContext}
    ${codeFilesInContext}
    ${analysisInContext}
    ${fixInContext}
  `.trim();

  tracker.measure('main_context', totalMainContext);
  tracker.measure('agent_output', ''); // No agent used
  tracker.measure('main_return', totalMainContext); // Everything in main
  tracker.measure('storage', '');
  tracker.measure('retrieval', '');

  return tracker;
}

/**
 * SCENARIO 3: Code Refactoring (Baseline - No Framework)
 *
 * WITHOUT framework:
 * - User reads all files that need refactoring
 * - Plans refactoring inline
 * - Writes all changes inline
 */
export function baselineScenario3_CodeRefactoring() {
  const tracker = createMeasurementTracker(
    'BASELINE-3',
    'Code Refactoring (No Framework)',
    { variant: 'baseline', framework: 'none' }
  );

  const mainInput = 'Refactor user service to use dependency injection pattern';
  tracker.measure('main_input', mainInput);

  // WITHOUT framework: Read all files to be refactored
  const existingCodeInContext = `
    // src/services/user.service.ts (current implementation - 250 lines)
    import { db } from '../config/database';
    import { emailService } from '../services/email.service';
    import { logger } from '../utils/logger';

    export class UserService {
      async createUser(data: CreateUserDto) {
        // Direct dependencies - tightly coupled
        const existing = await db.query('SELECT * FROM users WHERE email = $1', [data.email]);
        if (existing.rows.length > 0) {
          throw new Error('User exists');
        }

        const result = await db.query(
          'INSERT INTO users (email, name) VALUES ($1, $2) RETURNING *',
          [data.email, data.name]
        );

        const user = result.rows[0];

        // Direct call to email service
        await emailService.sendWelcomeEmail(user.email, user.name);

        logger.info('User created', { userId: user.id });

        return user;
      }

      async getUserById(id: string) {
        const result = await db.query('SELECT * FROM users WHERE id = $1', [id]);
        return result.rows[0];
      }

      async updateUser(id: string, data: UpdateUserDto) {
        const result = await db.query(
          'UPDATE users SET name = $1, email = $2 WHERE id = $3 RETURNING *',
          [data.name, data.email, id]
        );
        return result.rows[0];
      }

      async deleteUser(id: string) {
        await db.query('DELETE FROM users WHERE id = $1', [id]);
        logger.info('User deleted', { userId: id });
      }

      // ... 200 more lines with similar tight coupling
    }

    // Other files that import UserService
    // src/controllers/user.controller.ts (150 lines)
    import { UserService } from '../services/user.service';

    const userService = new UserService();

    export class UserController {
      async create(req: Request, res: Response) {
        const user = await userService.createUser(req.body);
        res.json(user);
      }
      // ... 130 more lines
    }

    // src/routes/user.routes.ts (80 lines)
    // tests/services/user.service.test.ts (200 lines - hard to test due to tight coupling)
  `.trim();

  // WITHOUT framework: Refactoring plan in main context
  const refactoringPlanInContext = `
    ## Refactoring Plan: Dependency Injection

    ### Goals
    1. Remove tight coupling to database, email service, logger
    2. Make UserService testable with dependency injection
    3. Allow different implementations for testing

    ### Changes Needed

    #### 1. Create Interfaces
    - IDatabase - abstract database operations
    - IEmailService - abstract email operations
    - ILogger - abstract logging operations

    #### 2. Update UserService
    - Accept dependencies via constructor
    - Use interfaces instead of concrete implementations
    - Remove global imports of db, emailService, logger

    #### 3. Create Container
    - Implement dependency injection container
    - Register all services
    - Manage service lifecycle

    #### 4. Update Consumers
    - Update UserController to use container
    - Update routes to use container
    - Update tests to use mocks

    ### Migration Strategy
    1. Create interfaces first
    2. Update UserService with backward compatibility
    3. Create DI container
    4. Update all consumers
    5. Remove old code
  `.trim();

  // WITHOUT framework: All refactored code in main context
  const refactoredCodeInContext = `
    // src/interfaces/database.interface.ts
    export interface IDatabase {
      query<T = any>(sql: string, params: any[]): Promise<{ rows: T[] }>;
    }

    // src/interfaces/email.interface.ts
    export interface IEmailService {
      sendWelcomeEmail(email: string, name: string): Promise<void>;
    }

    // src/interfaces/logger.interface.ts
    export interface ILogger {
      info(message: string, meta?: any): void;
      error(message: string, meta?: any): void;
    }

    // src/services/user.service.ts (refactored - 180 lines)
    import { IDatabase } from '../interfaces/database.interface';
    import { IEmailService } from '../interfaces/email.interface';
    import { ILogger } from '../interfaces/logger.interface';

    export class UserService {
      constructor(
        private db: IDatabase,
        private emailService: IEmailService,
        private logger: ILogger
      ) {}

      async createUser(data: CreateUserDto) {
        const existing = await this.db.query(
          'SELECT * FROM users WHERE email = $1',
          [data.email]
        );

        if (existing.rows.length > 0) {
          throw new Error('User exists');
        }

        const result = await this.db.query(
          'INSERT INTO users (email, name) VALUES ($1, $2) RETURNING *',
          [data.email, data.name]
        );

        const user = result.rows[0];

        await this.emailService.sendWelcomeEmail(user.email, user.name);

        this.logger.info('User created', { userId: user.id });

        return user;
      }

      // ... rest of methods refactored similarly
    }

    // src/container.ts (new file - 120 lines)
    import { Container } from 'typedi';
    import { db } from './config/database';
    import { emailService } from './services/email.service';
    import { logger } from './utils/logger';
    import { UserService } from './services/user.service';

    export function setupContainer() {
      Container.set('database', db);
      Container.set('emailService', emailService);
      Container.set('logger', logger);

      Container.set('userService', new UserService(
        Container.get('database'),
        Container.get('emailService'),
        Container.get('logger')
      ));
    }

    // src/controllers/user.controller.ts (updated - 150 lines)
    import { Container } from 'typedi';
    import { UserService } from '../services/user.service';

    export class UserController {
      private userService: UserService;

      constructor() {
        this.userService = Container.get('userService');
      }

      async create(req: Request, res: Response) {
        const user = await this.userService.createUser(req.body);
        res.json(user);
      }

      // ... rest of methods
    }

    // tests/services/user.service.test.ts (updated - 180 lines)
    import { UserService } from '../../src/services/user.service';

    describe('UserService', () => {
      let userService: UserService;
      let mockDb: IDatabase;
      let mockEmailService: IEmailService;
      let mockLogger: ILogger;

      beforeEach(() => {
        mockDb = {
          query: jest.fn()
        };
        mockEmailService = {
          sendWelcomeEmail: jest.fn()
        };
        mockLogger = {
          info: jest.fn(),
          error: jest.fn()
        };

        userService = new UserService(mockDb, mockEmailService, mockLogger);
      });

      it('should create user', async () => {
        mockDb.query.mockResolvedValueOnce({ rows: [] }); // No existing user
        mockDb.query.mockResolvedValueOnce({ rows: [{ id: '1', email: 'test@test.com' }] });

        const user = await userService.createUser({ email: 'test@test.com', name: 'Test' });

        expect(user).toBeDefined();
        expect(mockEmailService.sendWelcomeEmail).toHaveBeenCalled();
      });

      // ... more tests now much easier to write
    });
  `.trim();

  const totalMainContext = `
    ${mainInput}
    ${existingCodeInContext}
    ${refactoringPlanInContext}
    ${refactoredCodeInContext}
  `.trim();

  tracker.measure('main_context', totalMainContext);
  tracker.measure('agent_output', '');
  tracker.measure('main_return', totalMainContext);
  tracker.measure('storage', '');
  tracker.measure('retrieval', '');

  return tracker;
}

/**
 * SCENARIO 4: Session Resume (Baseline - No Framework)
 *
 * WITHOUT framework:
 * - User must re-read all context from previous session
 * - No persistent memory of decisions or progress
 * - Must scroll through chat history or notes
 */
export function baselineScenario4_SessionResume() {
  const tracker = createMeasurementTracker(
    'BASELINE-4',
    'Session Resume (No Framework)',
    { variant: 'baseline', framework: 'none' }
  );

  const mainInput = 'Continue working on the user dashboard feature from yesterday';
  tracker.measure('main_input', mainInput);

  // WITHOUT framework: User must manually provide all context from previous session
  const previousSessionContext = `
    ## Context from Previous Session (Yesterday)

    ### What We Were Working On
    Building a user dashboard with the following features:
    - User profile display
    - Recent activity feed
    - Quick stats (posts, followers, etc.)
    - Settings shortcut

    ### What We Completed
    1. Created dashboard layout component
    2. Implemented user profile section
    3. Added basic styling with Tailwind
    4. Set up data fetching with React Query

    ### Files Created/Modified
    - src/pages/Dashboard.tsx (created, 180 lines)
    - src/components/UserProfile.tsx (created, 120 lines)
    - src/components/ActivityFeed.tsx (created, 150 lines)
    - src/hooks/useDashboardData.ts (created, 80 lines)
    - src/types/dashboard.ts (created, 60 lines)

    ### Current State of Code

    // src/pages/Dashboard.tsx
    import React from 'react';
    import { UserProfile } from '../components/UserProfile';
    import { ActivityFeed } from '../components/ActivityFeed';
    import { useDashboardData } from '../hooks/useDashboardData';

    export function Dashboard() {
      const { user, activities, stats, isLoading } = useDashboardData();

      if (isLoading) return <div>Loading...</div>;

      return (
        <div className="dashboard">
          <UserProfile user={user} stats={stats} />
          <ActivityFeed activities={activities} />
          {/* TODO: Add QuickStats component */}
          {/* TODO: Add SettingsShortcut component */}
        </div>
      );
    }

    // src/components/UserProfile.tsx
    export function UserProfile({ user, stats }) {
      return (
        <div className="profile-card">
          <img src={user.avatar} alt={user.name} />
          <h2>{user.name}</h2>
          <p>{user.bio}</p>
          <div className="stats">
            <span>Posts: {stats.posts}</span>
            <span>Followers: {stats.followers}</span>
          </div>
        </div>
      );
    }

    // ... full code of all modified files (500+ lines total)

    ### What We Decided
    1. Use React Query for data fetching (considered SWR but chose React Query for better TypeScript support)
    2. Use Tailwind CSS (already in project)
    3. Component structure: Dashboard (page) → UserProfile, ActivityFeed, QuickStats (components)
    4. Data flow: useDashboardData hook → React Query → API

    ### Issues/Blockers Encountered
    1. TypeScript type errors with stats object - RESOLVED by creating proper types
    2. React Query cache invalidation not working - RESOLVED by fixing query keys
    3. Avatar images not loading - STILL OPEN (CORS issue with image CDN)

    ### What's Left to Do (from yesterday's notes)
    1. Create QuickStats component
    2. Create SettingsShortcut component
    3. Fix avatar CORS issue
    4. Add loading skeletons
    5. Add error handling
    6. Write tests
    7. Update documentation

    ### Design Decisions Still Pending
    - Should QuickStats be a separate component or part of UserProfile?
    - What stats should we show in QuickStats?
    - Should we add real-time updates to activity feed?

    ### Relevant API Endpoints
    GET /api/dashboard - returns { user, activities, stats }
    GET /api/user/profile - returns user profile
    GET /api/activities - returns recent activities

    ### Dependencies Added
    - @tanstack/react-query@5.0.0
    - Already had: react, tailwindcss, typescript

    ### Testing Notes
    - Manual testing done in browser
    - No automated tests yet
    - Works in Chrome, Safari - not tested in Firefox
  `.trim();

  // WITHOUT framework: User must also reload current file state
  const currentCodeState = `
    // Need to re-read all current files to understand state

    // src/pages/Dashboard.tsx (current state)
    [... paste full file again ...]

    // src/components/UserProfile.tsx (current state)
    [... paste full file again ...]

    // src/components/ActivityFeed.tsx (current state)
    [... paste full file again ...]

    // src/hooks/useDashboardData.ts (current state)
    [... paste full file again ...]

    // Total: Re-reading ~600 lines of code to understand current state
  `.trim();

  const totalMainContext = `
    ${mainInput}
    ${previousSessionContext}
    ${currentCodeState}
  `.trim();

  tracker.measure('main_context', totalMainContext);
  tracker.measure('agent_output', '');
  tracker.measure('main_return', totalMainContext);
  tracker.measure('storage', '');
  tracker.measure('retrieval', '');

  return tracker;
}

/**
 * SCENARIO 5: Multi-Agent Collaboration (Baseline - No Framework)
 *
 * WITHOUT framework:
 * - User must manually coordinate between different types of work
 * - All design artifacts, architecture docs, etc. in main context
 * - No structured handoff between phases
 */
export function baselineScenario5_MultiAgentCollaboration() {
  const tracker = createMeasurementTracker(
    'BASELINE-5',
    'Multi-Agent Collaboration (No Framework)',
    { variant: 'baseline', framework: 'none' }
  );

  const mainInput = 'Design and implement a real-time notification system';
  tracker.measure('main_input', mainInput);

  // WITHOUT framework: All design work happens inline in main context
  const architectureDesignInContext = `
    ## System Architecture for Real-Time Notifications

    ### Requirements Analysis
    1. Users must receive notifications in real-time
    2. Notifications should persist even if user is offline
    3. Multiple notification types: messages, mentions, system alerts
    4. Support for web and mobile clients
    5. Scalable to 100k concurrent users

    ### Architecture Decision Records

    #### ADR-001: WebSocket vs Server-Sent Events vs Long Polling
    **Decision:** Use WebSocket (Socket.io)
    **Rationale:**
    - Bidirectional communication needed
    - Better browser support than raw WebSockets
    - Built-in fallback mechanisms
    - Room support for targeted broadcasting

    #### ADR-002: Message Queue Selection
    **Decision:** Use Redis Pub/Sub with Redis Streams as fallback
    **Rationale:**
    - Already using Redis for caching
    - Pub/Sub sufficient for real-time delivery
    - Streams provide persistence for offline users
    - Better latency than RabbitMQ for our scale

    #### ADR-003: Database Schema
    **Decision:** Store notifications in PostgreSQL with Redis cache
    **Rationale:**
    - PostgreSQL for persistence and complex queries
    - Redis for fast delivery of recent notifications
    - Hybrid approach balances performance and reliability

    ### High-Level Architecture

    \`\`\`
    Client (Web/Mobile)
         ↓ WebSocket
    Load Balancer (nginx)
         ↓
    Socket.io Server (Node.js) ←→ Redis Pub/Sub
         ↓
    Notification Service
         ↓
    PostgreSQL + Redis Cache
    \`\`\`

    ### Components

    1. **Socket Server**
       - Handles WebSocket connections
       - Authenticates users via JWT
       - Subscribes to user-specific Redis channels
       - Broadcasts notifications to connected clients

    2. **Notification Service**
       - Receives notification requests via API
       - Validates and enriches notifications
       - Publishes to Redis Pub/Sub
       - Stores in PostgreSQL
       - Updates Redis cache

    3. **Persistence Layer**
       - PostgreSQL tables: notifications, user_notifications
       - Redis cache: recent notifications per user
       - Redis Streams: backup for offline delivery

    4. **Client Library**
       - Manages WebSocket connection
       - Handles reconnection logic
       - Queues notifications during offline periods
       - Syncs with server on reconnect

    ### Data Model

    \`\`\`sql
    CREATE TABLE notifications (
      id UUID PRIMARY KEY,
      type VARCHAR(50) NOT NULL,
      title VARCHAR(255) NOT NULL,
      body TEXT,
      data JSONB,
      created_at TIMESTAMP DEFAULT NOW(),
      expires_at TIMESTAMP
    );

    CREATE TABLE user_notifications (
      id UUID PRIMARY KEY,
      user_id UUID NOT NULL,
      notification_id UUID REFERENCES notifications(id),
      read BOOLEAN DEFAULT FALSE,
      read_at TIMESTAMP,
      delivered BOOLEAN DEFAULT FALSE,
      delivered_at TIMESTAMP,
      created_at TIMESTAMP DEFAULT NOW()
    );

    CREATE INDEX idx_user_notifications_user_id ON user_notifications(user_id);
    CREATE INDEX idx_user_notifications_read ON user_notifications(user_id, read);
    \`\`\`

    ### API Design

    #### WebSocket Events
    - \`connect\` - Client connects with JWT token
    - \`subscribe\` - Subscribe to notification channels
    - \`notification\` - Server sends notification to client
    - \`notification:read\` - Client marks notification as read
    - \`disconnect\` - Client disconnects

    #### REST API
    - POST /api/notifications - Create notification
    - GET /api/notifications - Get user's notifications
    - PUT /api/notifications/:id/read - Mark as read
    - DELETE /api/notifications/:id - Delete notification

    ### Scalability Considerations

    1. **Horizontal Scaling**
       - Multiple Socket.io servers behind load balancer
       - Redis Pub/Sub for cross-server communication
       - Sticky sessions for WebSocket connections

    2. **Performance**
       - Redis cache for recent notifications (last 100 per user)
       - PostgreSQL for historical data
       - Lazy loading of older notifications

    3. **Reliability**
       - Redis Streams as backup if Pub/Sub message lost
       - Client-side queuing during disconnection
       - Server-side retry logic

    ### Security

    1. JWT authentication for WebSocket connections
    2. Rate limiting on notification creation
    3. Validation of notification data
    4. XSS protection in notification content
    5. CORS configuration for WebSocket

    ### Monitoring & Observability

    - Metrics: connection count, message latency, delivery rate
    - Logging: connection events, errors, performance
    - Alerts: high latency, failed deliveries, connection spikes
  `.trim();

  // WITHOUT framework: All implementation details in main context
  const implementationDetailsInContext = `
    // src/socket/server.ts (280 lines)
    import { Server } from 'socket.io';
    import { createAdapter } from '@socket.io/redis-adapter';
    import { verifyToken } from '../utils/jwt';

    export function setupSocketServer(httpServer) {
      const io = new Server(httpServer, {
        cors: { origin: process.env.CORS_ORIGIN }
      });

      // Redis adapter for multi-server support
      const pubClient = createRedisClient();
      const subClient = pubClient.duplicate();
      io.adapter(createAdapter(pubClient, subClient));

      // Authentication middleware
      io.use(async (socket, next) => {
        const token = socket.handshake.auth.token;
        const user = await verifyToken(token);
        if (!user) return next(new Error('Authentication failed'));
        socket.userId = user.id;
        next();
      });

      // Connection handling
      io.on('connection', (socket) => {
        console.log(\`User connected: \${socket.userId}\`);

        // Subscribe to user's notification channel
        socket.join(\`user:\${socket.userId}\`);

        // Subscribe to Redis channel for this user
        const redis = createRedisClient();
        redis.subscribe(\`notifications:\${socket.userId}\`);
        redis.on('message', (channel, message) => {
          const notification = JSON.parse(message);
          socket.emit('notification', notification);
        });

        socket.on('notification:read', async (notificationId) => {
          await markNotificationRead(socket.userId, notificationId);
        });

        socket.on('disconnect', () => {
          console.log(\`User disconnected: \${socket.userId}\`);
          redis.unsubscribe();
          redis.quit();
        });
      });

      return io;
    }

    // ... 200 more lines of socket handling logic

    // src/services/notification.service.ts (320 lines)
    import { redis } from '../config/redis';
    import { db } from '../config/database';

    export class NotificationService {
      async createNotification(userId: string, notification: CreateNotificationDto) {
        // Validate notification
        this.validateNotification(notification);

        // Store in PostgreSQL
        const result = await db.query(
          'INSERT INTO notifications (type, title, body, data) VALUES ($1, $2, $3, $4) RETURNING *',
          [notification.type, notification.title, notification.body, notification.data]
        );
        const created = result.rows[0];

        // Link to user
        await db.query(
          'INSERT INTO user_notifications (user_id, notification_id) VALUES ($1, $2)',
          [userId, created.id]
        );

        // Cache in Redis
        await redis.lpush(
          \`notifications:\${userId}\`,
          JSON.stringify(created)
        );
        await redis.ltrim(\`notifications:\${userId}\`, 0, 99); // Keep last 100

        // Publish to Redis Pub/Sub for real-time delivery
        await redis.publish(
          \`notifications:\${userId}\`,
          JSON.stringify(created)
        );

        // Backup to Redis Streams (for offline users)
        await redis.xadd(
          \`stream:notifications:\${userId}\`,
          '*',
          'notification',
          JSON.stringify(created)
        );

        return created;
      }

      async getUserNotifications(userId: string, limit = 50, offset = 0) {
        // Try Redis cache first
        const cached = await redis.lrange(\`notifications:\${userId}\`, offset, offset + limit - 1);
        if (cached.length > 0) {
          return cached.map(n => JSON.parse(n));
        }

        // Fall back to database
        const result = await db.query(\`
          SELECT n.*, un.read, un.read_at
          FROM notifications n
          JOIN user_notifications un ON n.id = un.notification_id
          WHERE un.user_id = $1
          ORDER BY n.created_at DESC
          LIMIT $2 OFFSET $3
        \`, [userId, limit, offset]);

        return result.rows;
      }

      // ... 250 more lines of notification logic
    }

    // src/client/notification-client.ts (200 lines)
    import { io, Socket } from 'socket.io-client';

    export class NotificationClient {
      private socket: Socket;
      private offlineQueue: Notification[] = [];

      connect(token: string) {
        this.socket = io(process.env.SOCKET_URL, {
          auth: { token }
        });

        this.socket.on('connect', () => {
          console.log('Connected to notification server');
          this.syncOfflineNotifications();
        });

        this.socket.on('notification', (notification) => {
          if (navigator.onLine) {
            this.handleNotification(notification);
          } else {
            this.offlineQueue.push(notification);
          }
        });

        this.socket.on('disconnect', () => {
          console.log('Disconnected from notification server');
        });

        // Auto-reconnect logic
        this.socket.on('connect_error', () => {
          setTimeout(() => this.socket.connect(), 5000);
        });
      }

      private async syncOfflineNotifications() {
        // Fetch notifications missed while offline
        const lastSync = localStorage.getItem('lastNotificationSync');
        const notifications = await fetch(\`/api/notifications?since=\${lastSync}\`);
        // ... process missed notifications

        // Process offline queue
        while (this.offlineQueue.length > 0) {
          const notification = this.offlineQueue.shift();
          this.handleNotification(notification);
        }
      }

      // ... 150 more lines of client logic
    }
  `.trim();

  // WITHOUT framework: All testing strategy in main context
  const testingStrategyInContext = `
    ## Testing Strategy for Notification System

    ### Unit Tests

    1. **Notification Service Tests**
       - Test notification creation
       - Test validation logic
       - Test Redis caching
       - Test Pub/Sub publishing
       - Mock database and Redis

    2. **Socket Server Tests**
       - Test authentication
       - Test connection handling
       - Test message routing
       - Mock Socket.io client

    ### Integration Tests

    1. **End-to-End Flow**
       - Create notification → Publish → Deliver to client
       - Test with real Redis and PostgreSQL
       - Verify database state
       - Verify cache state

    2. **Offline Handling**
       - Disconnect client → Send notification → Reconnect → Verify delivery
       - Test Redis Streams fallback

    ### Load Tests

    1. **Concurrent Connections**
       - Simulate 10k concurrent users
       - Measure connection overhead
       - Measure message latency

    2. **Message Throughput**
       - Send 1000 notifications/second
       - Measure delivery latency
       - Verify no message loss

    ### Example Test Code

    \`\`\`typescript
    // tests/services/notification.service.test.ts
    describe('NotificationService', () => {
      it('should create and deliver notification', async () => {
        const service = new NotificationService();
        const notification = await service.createNotification('user-123', {
          type: 'message',
          title: 'New message',
          body: 'You have a new message'
        });

        expect(notification).toBeDefined();
        expect(notification.id).toBeTruthy();

        // Verify stored in database
        const stored = await db.query('SELECT * FROM notifications WHERE id = $1', [notification.id]);
        expect(stored.rows[0]).toBeDefined();

        // Verify published to Redis
        // ... verification logic
      });
    });
    \`\`\`
  `.trim();

  const totalMainContext = `
    ${mainInput}
    ${architectureDesignInContext}
    ${implementationDetailsInContext}
    ${testingStrategyInContext}
  `.trim();

  tracker.measure('main_context', totalMainContext);
  tracker.measure('agent_output', '');
  tracker.measure('main_return', totalMainContext);
  tracker.measure('storage', '');
  tracker.measure('retrieval', '');

  return tracker;
}

/**
 * Run all baseline scenarios and generate summary report
 */
export function runAllBaselineScenarios() {
  console.log('='.repeat(70));
  console.log('BASELINE MEASUREMENTS (No Claude Copilot Framework)');
  console.log('='.repeat(70));
  console.log('');
  console.log('Simulating token usage when:');
  console.log('- All code read directly into main context');
  console.log('- All plans written inline');
  console.log('- No agent delegation');
  console.log('- No Task Copilot storage');
  console.log('');
  console.log('='.repeat(70));
  console.log('');

  const scenarios = [
    { name: 'SCENARIO 1: Feature Implementation', fn: baselineScenario1_FeatureImplementation },
    { name: 'SCENARIO 2: Bug Investigation', fn: baselineScenario2_BugInvestigation },
    { name: 'SCENARIO 3: Code Refactoring', fn: baselineScenario3_CodeRefactoring },
    { name: 'SCENARIO 4: Session Resume', fn: baselineScenario4_SessionResume },
    { name: 'SCENARIO 5: Multi-Agent Collaboration', fn: baselineScenario5_MultiAgentCollaboration },
  ];

  const results = [];

  for (const scenario of scenarios) {
    console.log('-'.repeat(70));
    console.log(scenario.name);
    console.log('-'.repeat(70));
    console.log('');

    const tracker = scenario.fn();
    const summary = tracker.generateSummary();
    console.log(summary);
    console.log('');

    results.push({
      scenario: scenario.name,
      tracker: tracker,
      summary: summary,
      json: tracker.toJSON()
    });
  }

  console.log('='.repeat(70));
  console.log('SUMMARY: All Baseline Scenarios');
  console.log('='.repeat(70));
  console.log('');

  console.log('| Scenario | Main Context Tokens | Notes |');
  console.log('|----------|---------------------|-------|');

  for (const result of results) {
    const tokens = result.json.metrics.totalTokens.mainContext;
    const scenarioName = result.scenario.replace('SCENARIO ', '').substring(0, 30);
    console.log(`| ${scenarioName.padEnd(30)} | ${tokens.toLocaleString().padStart(19)} | All content in main |`);
  }

  console.log('');
  console.log('Key Observations:');
  console.log('1. WITHOUT framework, ALL content stays in main context');
  console.log('2. No compression or delegation to reduce token usage');
  console.log('3. Context bloat increases linearly with task complexity');
  console.log('4. Session resume requires re-loading full prior context');
  console.log('5. Multi-phase work requires keeping ALL artifacts in context');
  console.log('');

  return results;
}

// Run if executed directly
if (import.meta.url === `file://${process.argv[1]}`) {
  runAllBaselineScenarios();
}
