import { Body, Controller, Get, Header, HttpCode, Inject, Post, Query, Req, Res } from '@nestjs/common';
import type { Request, Response } from 'express';
import type { CommandRequest, LoginRequest } from '@shared/api.interface';
import { OwnerDatabaseContext } from './owner-database-context';
import { WorkbenchService } from './workbench.service';
import { requireOwner, sessionCookie, signSession } from './auth';

// Explicit owner password authentication, as requested, in addition to platform CSRF.
@Controller('api')
export class WorkbenchController {
  constructor(@Inject(WorkbenchService) private readonly service: WorkbenchService,
    @Inject(OwnerDatabaseContext) private readonly database: OwnerDatabaseContext) {}
  @Post('login') @HttpCode(200) @Header('Cache-Control', 'no-store')
  async login(@Req() req: Request, @Res({ passthrough: true }) res: Response, @Body() b: LoginRequest) {
    const token = await this.database.run(req,res,()=>this.service.login(b, req.ip || 'unknown'));
    res.setHeader('Set-Cookie', sessionCookie(token));
    return { ok: true };
  }
  @Post('logout') @HttpCode(200) @Header('Cache-Control', 'no-store')
  logout(@Res({ passthrough: true }) res: Response) {
    res.setHeader('Set-Cookie', sessionCookie('', true)); return { ok: true };
  }
  @Get('state') @Header('Cache-Control', 'no-store')
  state(@Req() req: Request, @Res({ passthrough: true }) res: Response) {
    const expires = requireOwner(req);
    if (expires < Date.now() + 75 * 86400000) res.setHeader('Set-Cookie', sessionCookie(signSession()));
    return this.database.run(req,res,()=>this.service.state());
  }
  @Post('commands') @HttpCode(200) @Header('Cache-Control', 'no-store')
  submit(@Req() req: Request, @Res({ passthrough: true }) res: Response, @Body() b: CommandRequest) { requireOwner(req); return this.database.run(req,res,()=>this.service.submit(b)); }
  @Get('history') @Header('Cache-Control', 'no-store')
  history(@Req() req: Request, @Res({passthrough:true}) res:Response,@Query('host') host:string,@Query('thread') thread:string){requireOwner(req);return this.database.run(req,res,()=>this.service.history(host,thread));}
  @Get('commands') @Header('Cache-Control', 'no-store')
  result(@Req() req: Request, @Res({ passthrough: true }) res: Response, @Query('id') id: string) { requireOwner(req); return this.database.run(req,res,()=>this.service.result(id)); }
  @Get('live') @Header('Cache-Control','no-store')
  live(@Req() req:Request,@Res({passthrough:true}) res:Response,@Query('after') after:string){requireOwner(req);return this.database.run(req,res,()=>this.service.live(Math.max(0,Number(after)||0)));}
}
