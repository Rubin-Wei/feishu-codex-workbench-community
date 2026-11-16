import { OwnerDatabaseContext } from './owner-database-context';
import { Module } from '@nestjs/common';
import { WorkbenchController } from './workbench.controller';
import { WorkbenchOpenapiController } from './workbench.openapi.controller';
import { WorkbenchService } from './workbench.service';
@Module({ controllers: [WorkbenchController, WorkbenchOpenapiController], providers: [WorkbenchService, OwnerDatabaseContext] })
export class WorkbenchModule {}
