import { Body, Controller, Header, HttpCode, Inject, Post } from '@nestjs/common';
import type { AgentRequest, AgentResponse } from '@shared/api.interface';
import { WorkbenchService } from './workbench.service';
// Gateway authenticates the scoped Authorization Bearer API key for this server-to-server endpoint.
@Controller('openapi/agent')
export class WorkbenchOpenapiController {
  constructor(@Inject(WorkbenchService) private readonly service: WorkbenchService) {}
  @Post() @HttpCode(200) @Header('Cache-Control', 'no-store')
  exchange(@Body() b: AgentRequest): Promise<AgentResponse> { return this.service.exchange(b); }
}
