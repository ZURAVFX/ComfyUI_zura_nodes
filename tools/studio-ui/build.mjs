import {build} from 'esbuild';
import fs from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import postcss from 'postcss';
const output=new URL('../../web/vendor/',import.meta.url);
await fs.mkdir(output,{recursive:true});
execFileSync(process.execPath,['node_modules/@tailwindcss/cli/dist/index.mjs','-i','components.css','-o','components.raw.css'],{stdio:'inherit'});
const css=postcss.parse(await fs.readFile('components.raw.css','utf8'));
// Scope every top-level component rule and flatten Tailwind's layers so the
// library can own these explicit classes alongside ComfyUI's unlayered styles.
css.walkAtRules('layer',rule=>rule.nodes?rule.replaceWith(...rule.nodes):rule.remove());
css.walkRules(rule=>{
 if(rule.parent.type==='atrule'&&/keyframes$/.test(rule.parent.name))return;
 if(rule.parent.type==='rule')return;
 rule.selectors=rule.selectors.map(s=>s.includes(':root')||s.includes(':host')?'#genj-studio[data-workspace]':`#genj-studio[data-workspace] ${s}`);
});
await fs.writeFile(new URL('studio-components.css',output),css.toString());
const bundlePath=new URL('studio-components.js',output);
await build({entryPoints:['components.js'],bundle:true,format:'esm',target:'es2022',minify:true,legalComments:'linked',outfile:bundlePath.pathname.replace(/^\/(\w:)/,'$1')});
let bundle=await fs.readFile(bundlePath,'utf8');
const parserWhitespace="Te=`[ \t\n\\f\\r]`";
if(!bundle.includes(parserWhitespace))throw new Error('The bundled HTML parser whitespace class changed; inspect it before normalising.');
bundle=bundle.replace(parserWhitespace,"Te=`[ \\t\\n\\f\\r]`");
const parserAttributeSpace="[^ \t\n\\f\\r";
if(!bundle.includes(parserAttributeSpace))throw new Error('The bundled HTML attribute parser changed; inspect it before normalising.');
bundle=bundle.replace(parserAttributeSpace,"[^ \\t\\n\\f\\r");
await fs.writeFile(bundlePath,bundle);
await fs.rm('components.raw.css');
console.log('Local Studio component bundles built.');
