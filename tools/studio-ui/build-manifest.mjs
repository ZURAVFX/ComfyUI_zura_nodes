import {buildStudioHostManifest} from './manifest-builder.mjs';

const manifest=await buildStudioHostManifest();
console.log(`Shared Studio host manifest built for ${manifest.backendVersion}.`);
