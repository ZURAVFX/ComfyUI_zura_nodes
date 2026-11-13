// Keep source-preserving work at or above the artist's captured raster. Model
// grids may move outwards, but this helper never silently downscales an
// otherwise supported source. Decoded results are restored by the caller.
export const SOURCE_MODEL_LIMITS = Object.freeze({
  minDimension: 256,
  maxDimension: 8192,
  maxPixels: 8_388_608,
  editAreaMaxPixels: 16 * 1024 * 1024,
});

const positiveInteger = (value, name) => {
  const number = Number(value);
  if (!Number.isSafeInteger(number) || number < 1) throw new Error(`${name} must be a positive whole number.`);
  return number;
};

export function ceilToGrid(value, quantum) {
  const size = positiveInteger(value, 'Image dimension');
  const step = positiveInteger(quantum, 'Resolution step');
  return Math.ceil(size / step) * step;
}

const ceilScaledToGrid = (value, scaleNumerator, scaleDenominator, quantum) => {
  const top = BigInt(value) * BigInt(scaleNumerator);
  const bottom = BigInt(scaleDenominator) * BigInt(quantum);
  return Number((top + bottom - 1n) / bottom) * quantum;
};

/**
 * Scale just enough for the requested minimum axis, then move both axes up to
 * the model grid. Using one shared scale preserves the source aspect instead of
 * independently stretching a short axis to the minimum.
 */
export function sourceAlignedRaster(sourceWidth, sourceHeight, {minDimension = 256, quantum = 16} = {}) {
  const width = positiveInteger(sourceWidth, 'Source width');
  const height = positiveInteger(sourceHeight, 'Source height');
  const minimum = positiveInteger(minDimension, 'Minimum dimension');
  const step = positiveInteger(quantum, 'Resolution step');
  const alignedMinimum = ceilToGrid(minimum, step);
  const shortSide = Math.min(width, height);
  if (shortSide >= alignedMinimum) {
    return { width: ceilToGrid(width, step), height: ceilToGrid(height, step) };
  }

  if (width <= height) {
    return {
      width: alignedMinimum,
      height: ceilScaledToGrid(height, alignedMinimum, width, step),
    };
  }
  return {
    width: ceilScaledToGrid(width, alignedMinimum, height, step),
    height: alignedMinimum,
  };
}

/**
 * Resolve captured source pixels into a supported processing raster.
 * Explicit operational limits are reported as Studio limits, not model claims.
 */
export function sourceModelRaster(
  source,
  {
    quantum = 16,
    minDimension = SOURCE_MODEL_LIMITS.minDimension,
    maxDimension = SOURCE_MODEL_LIMITS.maxDimension,
    maxPixels = SOURCE_MODEL_LIMITS.maxPixels,
    label = 'This image model',
  } = {},
) {
  const sourceWidth = positiveInteger(source?.width, 'Source width');
  const sourceHeight = positiveInteger(source?.height, 'Source height');
  const step = positiveInteger(quantum, 'Resolution step');
  const minimum = positiveInteger(minDimension, 'Minimum dimension');
  const maximum = positiveInteger(maxDimension, 'Maximum dimension');
  const pixelLimit = positiveInteger(maxPixels, 'Pixel limit');

  if (sourceWidth > maximum || sourceHeight > maximum || sourceWidth * sourceHeight > pixelLimit) {
    throw new Error(
      `${label} cannot process ${sourceWidth} × ${sourceHeight} within Studio's ` +
      `${maximum}-pixel side and ${(pixelLimit / 1024 / 1024).toFixed(2)} MP operational canvas ` +
      'without reducing the source. Choose a compatible model or prepare a smaller delivery.',
    );
  }

  const { width, height } = sourceAlignedRaster(sourceWidth, sourceHeight, {
    minDimension: minimum,
    quantum: step,
  });
  if (width > maximum || height > maximum || width * height > pixelLimit) {
    throw new Error(
      `${label} cannot align ${sourceWidth} × ${sourceHeight} to its ${step}-pixel grid ` +
      `within Studio's ${(pixelLimit / 1024 / 1024).toFixed(2)} MP operational canvas ` +
      'without reducing the source. Choose a compatible model.',
    );
  }

  return {
    width,
    height,
    sourceWidth,
    sourceHeight,
    exact: width === sourceWidth && height === sourceHeight,
    scaleX: width / sourceWidth,
    scaleY: height / sourceHeight,
  };
}

export function modelRasterOptions(recipe = {}, {editArea = false} = {}) {
  const quantum = recipe.sizeStep ?? 16;
  const minDimension = recipe.minDimension ?? SOURCE_MODEL_LIMITS.minDimension;
  const maxDimension = recipe.maxDimension ?? SOURCE_MODEL_LIMITS.maxDimension;
  const maxPixels = editArea
    ? recipe.editAreaMaxPixels ?? SOURCE_MODEL_LIMITS.editAreaMaxPixels
    : recipe.maxPixels ?? SOURCE_MODEL_LIMITS.maxPixels;
  return {
    quantum,
    minDimension,
    maxDimension,
    maxPixels,
    // The shared resolution controls already use these short names.
    step: quantum,
    min: minDimension,
    max: maxDimension,
    label: recipe.name || 'This image model',
  };
}

export function editSourceRaster(references, recipe = {}, {editArea = false} = {}) {
  const source = references?.[0];
  if (!Number.isSafeInteger(Number(source?.width)) || !Number.isSafeInteger(Number(source?.height))) {
    throw new Error('Image 1 dimensions are missing. Re-upload it so Studio can read its actual size.');
  }
  return sourceModelRaster(source, modelRasterOptions(recipe, {editArea}));
}

export function restoreSourceSize(width, height) {
  return {
    width: positiveInteger(width, 'Source width'),
    height: positiveInteger(height, 'Source height'),
    crop: 'disabled',
  };
}
