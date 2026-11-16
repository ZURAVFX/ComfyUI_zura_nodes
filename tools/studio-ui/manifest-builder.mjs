import fs from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import path from 'node:path';

const defaultWeb=new URL('../../web/',import.meta.url);
const defaultProject=new URL('../../pyproject.toml',import.meta.url);
const asURL=value=>value instanceof URL?value:pathToFileURL(path.resolve(value));

export async function buildStudioHostManifest({webDirectory=defaultWeb,projectFile=defaultProject}={}){
  const web=asURL(webDirectory),project=asURL(projectFile);
  if(!web.pathname.endsWith('/'))throw new Error('Studio web directory URL needs a trailing slash');
  const pyproject=await fs.readFile(project,'utf8');
  const backendVersion=pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1];
  const packageInit=await fs.readFile(new URL('./__init__.py',project),'utf8');
  const runtimeVersion=packageInit.match(/^__version__\s*=\s*"([^"]+)"/m)?.[1];
  if(!backendVersion||runtimeVersion!==backendVersion)throw new Error('pyproject.toml and __init__.py package versions must match');

  // The entry imports this generated module. No runtime file contains a
  // manually maintained package version, so the next public build stays in sync.
  await fs.writeFile(new URL('studio_host_version.js',web),`export const STUDIO_UI_VERSION=${JSON.stringify(backendVersion)};\n`);
  const files=[],assets=[];
  const imageFontSuffixes=new Set(['.png','.jpg','.jpeg','.webp','.svg','.woff','.woff2','.ttf']);
  const vendorSuffixes=new Set(['.js','.mjs','.css']);
  const blockedDirectories=new Set(['node_modules','workflows','workflow','private','work','tests']);
  const isRuntimeAsset=name=>name==='flux3_prompt_upsampling.json'||
    name.startsWith('vendor/')&&vendorSuffixes.has(path.extname(name).toLowerCase())||
    (name.startsWith('assets/')||name.startsWith('paintout_studio/assets/'))&&imageFontSuffixes.has(path.extname(name).toLowerCase());
  async function collect(directory,prefix=''){
    for(const entry of await fs.readdir(directory,{withFileTypes:true})){
      const name=prefix+entry.name,entryURL=new URL(name,web);
      if(entry.isDirectory()){if(!blockedDirectories.has(entry.name))await collect(entryURL,name+'/');continue;}
      if(name==='studio_host_manifest.json')continue;
      if(!name.startsWith('vendor/')&&/\.(?:js|css|html)$/.test(name))files.push(name);
      else if(isRuntimeAsset(name))assets.push(name);
    }
  }
  await collect(web);
  files.sort();assets.sort();
  // sourceSha256 hashes sorted UTF-8 relative paths, NUL, raw source bytes
  // with CRLF pairs normalised to LF, NUL. Latin-1 is a byte-preserving way
  // to replace those pairs, including in legacy files with non-UTF-8 bytes.
  const digest=createHash('sha256'),fileDigests={};
  for(const name of files){const bytes=await fs.readFile(new URL(name,web));digest.update(name+'\0');digest.update(Buffer.from(bytes.toString('latin1').replace(/\r\n/g,'\n'),'latin1'));digest.update('\0');fileDigests[name]=createHash('sha256').update(bytes).digest('hex');}
  const entryFiles=['studio_ae.html','studio_ae_probe.js','studio_ae_entry.js','studio_host_version.js'];
  for(const name of entryFiles)if(!fileDigests[name])throw new Error(`Studio host entry is missing: ${name}`);
  const entrySha256=Object.fromEntries(entryFiles.map(name=>[name,fileDigests[name]]));
  const assetSha256=Object.fromEntries(await Promise.all(assets.map(async name=>[name,createHash('sha256').update(await fs.readFile(new URL(name,web))).digest('hex')])));
  const manifest={hostSchema:1,uiVersion:backendVersion,backendVersion,sourceSha256:digest.digest('hex'),entrySha256,assetSha256,entries:{comfy:'studio.js',ae:'studio_ae.html'},sourceFiles:files};
  await fs.writeFile(new URL('studio_host_manifest.json',web),JSON.stringify(manifest,null,2)+'\n');
  return manifest;
}
