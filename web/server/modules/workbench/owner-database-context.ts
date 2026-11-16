import { Inject, Injectable } from '@nestjs/common';
import { SqlExecutionContextMiddleware } from '@lark-apaas/fullstack-nestjs-core';
import type { Request, Response } from 'express';

/**
 * Server-only database scope for our explicit password-authenticated owner API.
 * Browser/dataloom roles remain denied by RLS. Call only AFTER requireOwner,
 * except the fixed login handler which only reads/writes rate-limit counters.
 * Uses the platform's exported middleware and restores the original identity.
 */
@Injectable()
export class OwnerDatabaseContext {
  constructor(@Inject(SqlExecutionContextMiddleware) private readonly context: SqlExecutionContextMiddleware) {}
  run<T>(req: Request, res: Response, operation: () => Promise<T>): Promise<T> {
    const original = req.userContext;
    return new Promise<T>((resolve, reject) => {
      try {
        req.userContext = { ...original, isSystemAccount: true };
        this.context.use(req, res, () => {
          req.userContext = original;
          operation().then(resolve, reject);
        });
      } catch (error) { reject(error); }
      finally { req.userContext = original; }
    });
  }
}
