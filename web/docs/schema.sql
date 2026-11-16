CREATE TABLE workbench_command (
id uuid PRIMARY KEY DEFAULT gen_random_uuid(), request_id varchar(36) UNIQUE NOT NULL, action varchar(32) NOT NULL,
args text NOT NULL, status varchar(16) NOT NULL DEFAULT 'pending',
result text, created bigint NOT NULL, claimed bigint, completed bigint,
_created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
_created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
_updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
_updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
ALTER TABLE workbench_command ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_role_bypass_policy ON workbench_command TO service_role USING (true);
CREATE POLICY "修改全部数据" ON workbench_command AS PERMISSIVE FOR ALL TO authenticated USING (false);
CREATE POLICY "查看全部数据" ON workbench_command AS PERMISSIVE FOR SELECT TO authenticated, anon USING (false);
CREATE POLICY "修改本人数据" ON workbench_command AS PERMISSIVE FOR ALL TO authenticated USING (false);

CREATE TABLE workbench_snapshot (
id uuid PRIMARY KEY DEFAULT gen_random_uuid(), key varchar(32) UNIQUE NOT NULL, payload text NOT NULL, seen_at bigint NOT NULL,
_created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
_created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
_updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
_updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
ALTER TABLE workbench_snapshot ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_role_bypass_policy ON workbench_snapshot TO service_role USING (true);
CREATE POLICY "修改全部数据" ON workbench_snapshot AS PERMISSIVE FOR ALL TO authenticated USING (false);
CREATE POLICY "查看全部数据" ON workbench_snapshot AS PERMISSIVE FOR SELECT TO authenticated, anon USING (false);
CREATE POLICY "修改本人数据" ON workbench_snapshot AS PERMISSIVE FOR ALL TO authenticated USING (false);

CREATE TABLE workbench_login (
id uuid PRIMARY KEY DEFAULT gen_random_uuid(), bucket varchar(255) UNIQUE NOT NULL, attempts integer NOT NULL DEFAULT 0, expires_at bigint NOT NULL,
_created_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
_created_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END),
_updated_at TIMESTAMP(3) WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
_updated_by user_profile DEFAULT (CASE WHEN current_setting('app.user_id', TRUE) = '' THEN NULL ELSE concat('(', current_setting('app.user_id', TRUE), ')')::user_profile END)
);
ALTER TABLE workbench_login ENABLE ROW LEVEL SECURITY;
CREATE POLICY service_role_bypass_policy ON workbench_login TO service_role USING (true);
CREATE POLICY "修改全部数据" ON workbench_login AS PERMISSIVE FOR ALL TO authenticated USING (false);
CREATE POLICY "查看全部数据" ON workbench_login AS PERMISSIVE FOR SELECT TO authenticated, anon USING (false);
CREATE POLICY "修改本人数据" ON workbench_login AS PERMISSIVE FOR ALL TO authenticated USING (false);
