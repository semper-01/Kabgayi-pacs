import assert from 'node:assert/strict';
import { readFileSync, writeFileSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { resolve } from 'node:path';

const sourceRoot = resolve(process.argv[2] ?? '.');
const expectedCommit = 'e844561fa487dc8f572643b6aa6584fd806e60d3';
const actualCommit = execFileSync('git', ['rev-parse', 'HEAD'], {
  cwd: sourceRoot,
  encoding: 'utf8',
}).trim();

assert.equal(actualCommit, expectedCommit, 'OHIF source commit does not match the pinned release.');

const packagePath = resolve(sourceRoot, 'package.json');
const rootPackage = JSON.parse(readFileSync(packagePath, 'utf8'));
assert.equal(rootPackage.version, '3.13.12');
assert.equal(rootPackage.packageManager, 'pnpm@12.8.1');

const appPackage = JSON.parse(
  readFileSync(resolve(sourceRoot, 'platform/app/package.json'), 'utf8'),
);
assert.equal(appPackage.dependencies['@cornerstonejs/dicom-image-loader'], '5.6.8');

const lockfile = readFileSync(resolve(sourceRoot, 'pnpm-lock.yaml'), 'utf8');
assert.match(lockfile, /^  '@cornerstonejs\/dicom-image-loader@5\.6\.8':/m);
assert.match(lockfile, /^  '@cornerstonejs\/metadata@5\.6\.8':/m);

const workspaceConfigPath = resolve(sourceRoot, 'pnpm-workspace.yaml');
let workspaceConfig = readFileSync(workspaceConfigPath, 'utf8');
assert.doesNotMatch(
  workspaceConfig,
  /^patchedDependencies:/m,
  'Unexpected existing patchedDependencies section; merge it explicitly.',
);

const overrideSection = /^overrides:\s*$/m.exec(workspaceConfig);
assert.ok(overrideSection, 'Could not locate pnpm-workspace.yaml overrides section.');
const patchConfig = [
  'patchedDependencies:',
  "  '@cornerstonejs/dicom-image-loader@5.6.8': patches/kabgayi/@cornerstonejs__dicom-image-loader@5.6.8.patch",
  "  '@cornerstonejs/metadata@5.6.8': patches/kabgayi/@cornerstonejs__metadata@5.6.8.patch",
  '',
].join('\n');
workspaceConfig = `${workspaceConfig.slice(0, overrideSection.index)}${patchConfig}${workspaceConfig.slice(overrideSection.index)}`;
writeFileSync(workspaceConfigPath, workspaceConfig);

console.log(`Prepared OHIF v${rootPackage.version} at ${actualCommit} with the pinned Cornerstone patches.`);
