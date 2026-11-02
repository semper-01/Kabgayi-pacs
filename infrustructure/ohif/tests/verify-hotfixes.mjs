import assert from 'node:assert/strict';
import { readFileSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const sourceRoot = resolve(process.argv[2] ?? '.');
const packageJson = name =>
  JSON.parse(
    readFileSync(resolve(sourceRoot, 'node_modules', ...name.split('/'), 'package.json'), 'utf8'),
  );

assert.equal(packageJson('@cornerstonejs/dicom-image-loader').version, '5.6.8');
assert.equal(packageJson('@cornerstonejs/metadata').version, '5.6.8');

const imageLoaderSource = readFileSync(
  resolve(
    sourceRoot,
    'node_modules/@cornerstonejs/dicom-image-loader/dist/esm/imageLoader/createImage.js',
  ),
  'utf8',
);
const voiField = imageLoaderSource.indexOf('voiLUTFunction: (() => {');
const voiStart = imageLoaderSource.indexOf(':', voiField) + 1;
const voiEnd = imageLoaderSource.indexOf('})(),', voiStart);
assert.ok(voiField >= 0 && voiStart > 0 && voiEnd > voiStart, 'Patched VOI LUT expression was not found.');

const normalizeVOILUTFunction = new Function(
  'voiLutModule',
  `return (${imageLoaderSource.slice(voiStart, voiEnd + 4)});`,
);
assert.equal(normalizeVOILUTFunction({ voiLUTFunction: 'LINEAR' }), 'LINEAR');
assert.equal(normalizeVOILUTFunction({ voiLUTFunction: 'SIGMOID' }), 'SIGMOID');
assert.equal(normalizeVOILUTFunction({ voiLUTFunction: ' SIGMOID ' }), 'SIGMOID');
assert.equal(normalizeVOILUTFunction({ voiLUTFunction: ['LINEAR'] }), 'LINEAR');
assert.equal(normalizeVOILUTFunction({ voiLUTFunction: '' }), undefined);
assert.equal(normalizeVOILUTFunction({ voiLUTFunction: undefined }), undefined);

const metadataPath = resolve(
  sourceRoot,
  'node_modules/@cornerstonejs/metadata/dist/esm/utilities/getPixelSpacingInformation.js',
);
const { calculateRadiographicPixelSpacing, getERMF, getPixelSpacingInformation } =
  await import(pathToFileURL(metadataPath).href);
const projectionSOPClassUID = '1.2.840.10008.5.1.4.1.1.1';
const suppliedPixelSpacing = [0.25, 0.3];
const imagerPixelSpacing = [0.5, 0.6];
const invalidDistances = [
  ['missing', undefined, false],
  ['null', null, true],
  ['zero', 0, true],
  ['zero string', '0', true],
  ['negative', -1, true],
  ['blank', '', true],
  ['NaN', NaN, true],
  ['infinite', Infinity, true],
  ['invalid string', 'invalid', true],
];

for (const [label, sourceToPatient, includeDistance] of invalidDistances) {
  const instance = {
    SOPClassUID: projectionSOPClassUID,
    DistanceSourceToDetector: 1000,
    PixelSpacing: suppliedPixelSpacing,
    ImagerPixelSpacing: imagerPixelSpacing,
  };
  if (includeDistance) {
    instance.DistanceSourceToPatient = sourceToPatient;
  }

  const magnification = getERMF(instance);
  assert.ok(
    magnification === true || magnification === undefined,
    `${label} source-to-patient distance produced a numeric magnification.`,
  );
  assert.deepEqual(
    getPixelSpacingInformation(instance).PixelSpacing,
    suppliedPixelSpacing,
    `${label} source-to-patient distance changed valid PixelSpacing.`,
  );
}

const validDistanceInstance = {
  SOPClassUID: projectionSOPClassUID,
  DistanceSourceToDetector: 1000,
  DistanceSourceToPatient: 500,
  PixelSpacing: suppliedPixelSpacing,
  ImagerPixelSpacing: imagerPixelSpacing,
};
assert.equal(getERMF(validDistanceInstance), 2);
assert.deepEqual(
  calculateRadiographicPixelSpacing(validDistanceInstance).PixelSpacing,
  suppliedPixelSpacing,
  'Valid source distances should retain the expected supplied pixel spacing.',
);

const distPath = resolve(sourceRoot, 'platform/app/dist');
const bundleNames = readdirSync(distPath).filter(
  name => name.startsWith('app.bundle.') && name.endsWith('.js'),
);
assert.ok(bundleNames.length > 0, 'Production OHIF app bundle was not found.');
const bundles = bundleNames.map(name => readFileSync(resolve(distPath, name), 'utf8'));
assert.ok(
  bundles.some(bundle => bundle.includes('rawVOILUTFunction = voiLutModule.voiLUTFunction')),
  'Production bundle is missing the scalar VOI LUT fix.',
);
assert.ok(
  bundles.some(
    bundle =>
      bundle.includes('Number.isFinite(sourceToPatient)') &&
      bundle.includes('sourceToDetector > sourceToPatient'),
  ),
  'Production bundle is missing the guarded distance magnification fix.',
);

console.log('PASS: VOI LUT scalar and array regression cases.');
console.log('PASS: invalid distances are rejected and supplied PixelSpacing is preserved.');
console.log('PASS: valid distance magnification behavior is retained.');
console.log('PASS: both fixes are present in the production OHIF bundle.');
