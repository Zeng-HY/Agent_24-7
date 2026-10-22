import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { parseDocument } from 'yaml';
const doc = parseDocument(await readFile('../codemagic.yaml', 'utf8'), { uniqueKeys: true });
assert.equal(doc.errors.length, 0);
const workflow = doc.toJS().workflows['ios-simulator'];
assert.equal(workflow.instance_type, 'mac_mini_m2');
assert.equal(workflow.environment.node, '24.14.0');
assert.equal(String(workflow.environment.xcode), '26.2');
assert.equal(workflow.max_build_duration, 30);
assert.equal(workflow.triggering, undefined);
assert.equal(workflow.publishing, undefined);
assert.deepEqual(workflow.artifacts, ['mobile/build/AgentRemote-simulator.zip', 'mobile/build/Package.resolved']);
assert.equal(workflow.scripts[0].script, 'bash mobile/scripts/build-ios.sh');
const device = doc.toJS().workflows['ios-sideload'];
for (const key of ['instance_type', 'max_build_duration', 'environment']) assert.deepEqual(device[key], workflow[key]);
assert.equal(device.triggering, undefined);
assert.equal(device.publishing, undefined);
assert.equal(device.scripts[0].script, 'bash mobile/scripts/build-ios.sh device');
assert.deepEqual(device.artifacts, ['mobile/build/AgentRemote-unsigned.ipa', 'mobile/build/Package.resolved']);
const config = JSON.parse(await readFile('capacitor.config.json', 'utf8'));
assert.equal(config.server, undefined);
const pkg = JSON.parse(await readFile('package.json', 'utf8'));
const lock = JSON.parse(await readFile('package-lock.json', 'utf8'));
for (const group of ['dependencies', 'devDependencies']) {
  for (const [name, version] of Object.entries(pkg[group])) {
    assert.match(version, /^\d+\.\d+\.\d+$/);
    assert.equal(lock.packages['node_modules/' + name].version, version);
  }
}
console.log('YAML structure, fixed versions, unsigned/manual-only workflow and artifact scope checked locally.');
