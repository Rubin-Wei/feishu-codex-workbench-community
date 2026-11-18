import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {fileURLToPath} from 'node:url';
import ts from 'typescript';

// Exercise the browser-independent functions from their real source without
// adding a browser runner or importing components that require Miaoda runtime.
function loadExports(relativePath, functionName) {
  const file = fileURLToPath(new URL(relativePath, import.meta.url));
  let source = readFileSync(file, 'utf8');
  if (functionName) {
    const ast = ts.createSourceFile(file, source, ts.ScriptTarget.Latest, true);
    const declaration = ast.statements.find(statement =>
      ts.isFunctionDeclaration(statement) && statement.name?.text === functionName);
    assert.ok(declaration, `Expected exported function ${functionName}`);
    source = declaration.getText(ast);
  }
  const compiled = ts.transpileModule(source, {
    compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022},
    reportDiagnostics: true,
  });
  assert.equal(compiled.diagnostics?.length, 0, `Unable to transpile ${file}`);
  const exported = {};
  new Function('exports', compiled.outputText)(exported);
  return exported;
}

const {fileTarget} = loadExports('../client/src/pages/workbench/file-links.ts');
const accepted = [
  ['/workspace/app.py:12', {path: '/workspace/app.py', line: 12}],
  ['/workspace/app.py:12:3', {path: '/workspace/app.py', line: 12}],
  ['/workspace/My%20Report.md:3', {path: '/workspace/My Report.md', line: 3}],
  ['/workspace/app.py%3A12', {path: '/workspace/app.py', line: 12}],
  ['./src/main.ts#L12-L18', {path: './src/main.ts', line: 12}],
  ['./src/main.ts#L12C3-L18C5', {path: './src/main.ts', line: 12}],
  ['../reports/a.txt', {path: '../reports/a.txt'}],
  ['README.md', {path: 'README.md'}],
  ['Makefile', {path: 'Makefile'}],
  ['LICENSE', {path: 'LICENSE'}],
  ['src/Dockerfile', {path: 'src/Dockerfile'}],
  ['file:///workspace/app.py#L3', {path: '/workspace/app.py', line: 3}],
  ['file://localhost/workspace/app.py', {path: '/workspace/app.py'}],
  ['sandbox:/workspace/chart.png', {path: '/workspace/chart.png'}],
  [' /workspace/中文说明.md ', {path: '/workspace/中文说明.md'}],
];
for (const [href, expected] of accepted) {
  assert.deepEqual(fileTarget(href), expected, `Local file link: ${href}`);
}

const excluded = [
  '', '#L3', '//example.com/a.txt', 'https://example.com/a.txt:12',
  'http://example.com/a.txt', 'mailto:test@example.com', 'tel:+861234',
  'file://remote/workspace/app.py', 'javascript:alert(1)',
  'data:text/html,<script>alert(1)</script>', 'blob:https://example.com/id',
  '/workspace/a%00b.txt', '/workspace/a%0Ab.txt', '/workspace/a%ZZ.txt',
  '/workspace/file.txt?download=1', '/workspace/file.txt#section',
  '%2F%2Fexample.com/file.txt', 'javascript%3Aalert(1)',
];
for (const href of excluded) {
  assert.equal(fileTarget(href), null, `Non-file or malformed link: ${href}`);
}

const {resetLabel} = loadExports('../client/src/pages/workbench/AccountUsage.tsx', 'resetLabel');
const now = Date.UTC(2026, 10, 18, 12);
const countdowns = [
  [null, '重置时间暂不可用'],
  [(now - 1000) / 1000, '等待额度更新'],
  [now / 1000, '等待额度更新'],
  [(now + 1) / 1000, '1 分钟后重置'],
  [(now + 90_000) / 1000, '2 分钟后重置'],
  [(now + 3_600_000) / 1000, '1 小时后重置'],
  [(now + 86_400_000) / 1000, '1 天后重置'],
  [(now + 2 * 86_400_000 + 3 * 3_600_000) / 1000, '2 天 3 小时后重置'],
];
for (const [resetsAt, expected] of countdowns) {
  assert.equal(resetLabel(resetsAt, now), expected, `Reset countdown: ${resetsAt}`);
}

process.stdout.write(`File links: ${accepted.length + excluded.length} cases; reset countdown: ${countdowns.length} cases passed.\n`);
