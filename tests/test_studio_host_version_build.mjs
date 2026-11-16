import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash} from 'node:crypto';
import {buildStudioHostManifest} from '../tools/studio-ui/manifest-builder.mjs';

const root=await fs.mkdtemp(path.join(os.tmpdir(),'zura-studio-host-version-'));
try{
  const web=path.join(root,'web');await fs.mkdir(web);
  const project=path.join(root,'pyproject.toml');
  await fs.writeFile(project,'[project]\nname = "comfyui-zura-nodes"\nversion = "1.3.66"\n');
  await fs.writeFile(path.join(root,'__init__.py'),'__version__ = "1.3.66"\n');
  await fs.writeFile(path.join(web,'studio.js'),'import {mountStudio} from "./studio_core.js";\n');
  await fs.writeFile(path.join(web,'studio_ae.html'),'<script type="module" src="./studio_ae_entry.js"></script>\n');
  await fs.writeFile(path.join(web,'studio_ae_probe.js'),'import("./studio_ae_entry.js");\n');
  await fs.writeFile(path.join(web,'studio_ae_entry.js'),'export const entry=true;\n');
  await fs.mkdir(path.join(web,'vendor'));await fs.mkdir(path.join(web,'assets'));
  await fs.writeFile(path.join(web,'vendor','studio-components.js'),'export const component=true;\n');
  await fs.writeFile(path.join(web,'assets','zura-logo.png'),Buffer.from([137,80,78,71]));
  const options={webDirectory:pathToFileURL(web+path.sep),projectFile:pathToFileURL(project)};
  const manifest=await buildStudioHostManifest(options);
  const module=await import(pathToFileURL(path.join(web,'studio_host_version.js')).href);
  assert.equal(module.STUDIO_UI_VERSION,'1.3.66');
  assert.equal(manifest.uiVersion,module.STUDIO_UI_VERSION);
  assert.equal(manifest.backendVersion,'1.3.66');
  assert.ok(manifest.sourceFiles.includes('studio_host_version.js'));
  for(const name of ['studio_ae.html','studio_ae_probe.js','studio_ae_entry.js','studio_host_version.js']){
    const expected=createHash('sha256').update(await fs.readFile(path.join(web,name))).digest('hex');
    assert.equal(manifest.entrySha256[name],expected,`${name} is verified from served bytes`);
  }
  for(const name of ['vendor/studio-components.js','assets/zura-logo.png']){
    const expected=createHash('sha256').update(await fs.readFile(path.join(web,name))).digest('hex');
    assert.equal(manifest.assetSha256[name],expected,`${name} has a raw runtime asset digest`);
  }
  const repeated=await buildStudioHostManifest(options);
  assert.equal(repeated.sourceSha256,manifest.sourceSha256,'The same source builds the same host digest');
  await fs.writeFile(path.join(web,'studio.js'),'import {mountStudio} from "./studio_core.js";\r\n');
  const windows=await buildStudioHostManifest(options);
  assert.equal(windows.sourceSha256,manifest.sourceSha256,'Windows and Linux line endings produce the same source digest');
  await fs.writeFile(path.join(root,'__init__.py'),'__version__ = "1.3.65"\n');
  await assert.rejects(()=>buildStudioHostManifest(options),/versions must match/);
  const adapters=await fs.readFile(new URL('../web/studio_host_adapters.js',import.meta.url),'utf8');
  const entry=await fs.readFile(new URL('../web/studio_ae_entry.js',import.meta.url),'utf8');
  assert.match(adapters,/import \{STUDIO_UI_VERSION\} from '\.\/studio_host_version\.js'/);
  assert.ok(entry.includes('STUDIO_UI_VERSION')&&entry.includes("from './studio_host_adapters.js'"));
  assert.doesNotMatch(adapters,/1\.3\.65|1\.3\.66/,'The public host contract reads the generated version');
  assert.doesNotMatch(entry,/1\.3\.65|1\.3\.66/,'The AE entry reads the host contract version');
  console.log('Synthetic 1.3.66 build updates the shared UI version and manifest deterministically.');
}finally{
  if(path.dirname(root)!==os.tmpdir())throw new Error('Unexpected temporary test path');
  await fs.rm(root,{recursive:true,force:true});
}
