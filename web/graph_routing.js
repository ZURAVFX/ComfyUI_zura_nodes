// Small orthogonal router for the remaining fixed-port crossings inside stages.
// It moves wires only. Native nodes, sockets and inference inputs stay intact.
class Heap {
  items=[];
  push(item){const a=this.items;let i=a.length;a.push(item);while(i){const p=(i-1)>>1;if(a[p].score<=item.score)break;a[i]=a[p];i=p;}a[i]=item;}
  pop(){const a=this.items,first=a[0],last=a.pop();if(a.length){let i=0;while(i*2+1<a.length){let c=i*2+1;if(c+1<a.length&&a[c+1].score<a[c].score)c++;if(a[c].score>=last.score)break;a[i]=a[c];i=c;}a[i]=last;}return first;}
}

function simplify(points){
  const result=[];
  for(const p of points){if(result.length&&p.x===result.at(-1).x&&p.y===result.at(-1).y)continue;
    while(result.length>1){const a=result.at(-2),b=result.at(-1);if(a.x===b.x&&b.x===p.x||a.y===b.y&&b.y===p.y)result.pop();else break;}
    result.push(p);
  }return result;
}

export function crossingEdgeIds(layout){
  const edges=(layout.edges||[]).map(e=>({id:e.id,source:e.sources?.[0],target:e.targets?.[0],segments:(e.sections||[]).flatMap(s=>{
    const p=[s.startPoint,...s.bendPoints||[],s.endPoint];return p.slice(1).map((b,i)=>[p[i],b]);})}));
  const involved=new Set();
  for(let i=0;i<edges.length;i++)for(let j=i+1;j<edges.length;j++){
    if(edges[i].source===edges[j].source||edges[i].target===edges[j].target)continue;
    const between=(v,a,b)=>v>=Math.min(a,b)&&v<=Math.max(a,b);
    const overlap=(a,b,c,d)=>Math.max(Math.min(a,b),Math.min(c,d))<=Math.min(Math.max(a,b),Math.max(c,d));
    if(edges[i].segments.some(([a,b])=>edges[j].segments.some(([c,d])=>{
      const av=a.x===b.x,cv=c.x===d.x;
      if(av===cv)return av?a.x===c.x&&overlap(a.y,b.y,c.y,d.y):a.y===c.y&&overlap(a.x,b.x,c.x,d.x);
      const v=av?[a,b]:[c,d],h=av?[c,d]:[a,b];
      return between(v[0].x,h[0].x,h[1].x)&&between(h[0].y,v[0].y,v[1].y);
    }))){
      if(!involved.has(edges[i].id))involved.add(edges[i].id);
      if(!involved.has(edges[j].id))involved.add(edges[j].id);
    }
  }
  return [...involved];
}

// Targeted fallback: reroute ONE crossing wire around all others, which stay fixed.
// Used when full multi-wire routing saturates (e.g. H3 viewport prompt wire).
// Wires only; nodes, sockets and inference inputs are untouched.
export function rerouteSingleEdge(layout, edgeId){
  const target=layout.edges.find(e=>String(e.id)===String(edgeId));
  if(!target||target.sections?.length!==1)return null;
  const nodes=new Map(layout.children.map(n=>[n.id,n]));
  const step=5,pad=280;
  const minX=Math.floor((Math.min(...layout.children.map(n=>n.x))-pad)/step)*step;
  const minY=Math.floor((Math.min(...layout.children.map(n=>n.y))-pad)/step)*step;
  const width=Math.ceil((Math.max(...layout.children.map(n=>n.x+n.width))-minX+pad)/step)+1;
  const height=Math.ceil((Math.max(...layout.children.map(n=>n.y+n.height))-minY+pad)/step)+1;
  if(width*height>800000)return null;
  const xy=p=>[Math.round((p.x-minX)/step),Math.round((p.y-minY)/step)];
  const point=cell=>({x:minX+(cell%width)*step,y:minY+Math.floor(cell/width)*step});
  const cell=p=>{const [x,y]=xy(p);return y*width+x;};
  const blocked=new Uint8Array(width*height);
  const wireBlocked=new Uint8Array(width*height);
  for(const n of layout.children){const [a,b]=xy({x:n.x-10,y:n.y-10}),[c,d]=xy({x:n.x+n.width+10,y:n.y+n.height+10});
    for(let y=Math.max(0,b);y<=Math.min(height-1,d);y++)for(let x=Math.max(0,a);x<=Math.min(width-1,c);x++)blocked[y*width+x]=1;
  }
  // Freeze every other wire as an obstacle (rasterize its centerline cells).
  // Wires sharing the rerouted wire's source may share its trunk: the crossing
  // check skips same-source pairs, so those cells stay open to this owner.
  const owner=target.sources[0];
  const frozenOwner=new Map();
  for(const e of layout.edges){
    if(String(e.id)===String(edgeId))continue;
    for(const s of e.sections||[]){
      const pts=[s.startPoint,...s.bendPoints||[],s.endPoint];
      for(let i=1;i<pts.length;i++){
        const [x1,y1]=xy(pts[i-1]),[x2,y2]=xy(pts[i]);
        let x=x1,y=y1;
        for(let guard=0;guard<10000;guard++){
          if(x>=0&&x<width&&y>=0&&y<height){
            const id=y*width+x;
            if(e.sources[0]===owner){if(!blocked[id])frozenOwner.set(id,owner);}
            else{blocked[id]=1;wireBlocked[id]=1;}
          }
          if(x!==x2)x+=Math.sign(x2-x);else if(y!==y2)y+=Math.sign(y2-y);else break;
        }
      }
    }
  }
  const cellBlocked=id=>blocked[id]||(frozenOwner.has(id)&&frozenOwner.get(id)!==owner);
  const s=target.sections[0];
  const source=nodes.get(target.sources[0].replace(/:(?:in|out):\d+$/,"")),dest=nodes.get(target.targets[0].replace(/:(?:in|out):\d+$/,"") );
  if(!source||!dest)return null;
  const startC=cell({x:minX+Math.ceil((source.x+source.width+30-minX)/step)*step,y:s.startPoint.y});
  const endC=cell({x:minX+Math.floor((dest.x-30-minX)/step)*step,y:s.endPoint.y});
  const prefix=[s.startPoint,{x:minX+Math.ceil((source.x+source.width+30-minX)/step)*step,y:s.startPoint.y},point(startC)];
  const suffix=[point(endC),{x:minX+Math.floor((dest.x-30-minX)/step)*step,y:s.endPoint.y},s.endPoint];
  // Prefix/suffix stubs leave their own sockets, so they may cross the socket's
  // own node-inflation band; they must not cut through frozen wires.
  for(const path of [prefix,suffix])for(let i=1;i<path.length;i++){
    const [x1,y1]=xy(path[i-1]),[x2,y2]=xy(path[i]);
    let x=x1,y=y1;
    for(let guard=0;guard<1000;guard++){
      if(x>=0&&x<width&&y>=0&&y<height&&wireBlocked[y*width+x])return null;
      if(x!==x2)x+=Math.sign(x2-x);else if(y!==y2)y+=Math.sign(y2-y);else break;
    }
  }
  const heap=new Heap(),cost=new Map(),parents=new Map(),endPt=point(endC);
  const hkey=(id)=>id;
  heap.push({id:startC*4,score:0,g:0});cost.set(startC*4,0);
  let found;
  while(heap.items.length){
    const cur=heap.pop();if(cur.g!==cost.get(hkey(cur.id)))continue;
    const at=Math.floor(cur.id/4),dir=cur.id%4;if(at===endC){found=cur.id;break;}
    const x=at%width,y=Math.floor(at/width);        for(const [dx,dy,nd] of [[1,0,0],[0,1,1],[-1,0,2],[0,-1,3]]){
          const nx=x+dx,ny=y+dy;if(nx<0||nx>=width||ny<0||ny>=height)continue;
          if(cellBlocked(ny*width+nx))continue;
      const id=(ny*width+nx)*4+nd,g=cur.g+1+(dir===nd?0:.35);
      if(g>=(cost.get(id)??Infinity))continue;
      cost.set(id,g);parents.set(id,cur.id);
      const p=point(ny*width+nx);
      heap.push({id,g,score:g+(Math.abs(p.x-endPt.x)+Math.abs(p.y-endPt.y))/step});
    }
  }
  if(found===undefined)return null;
  const path=[];for(let id=found;id!==undefined;id=parents.get(id))path.push(point(Math.floor(id/4)));path.reverse();
  const full=simplify([...prefix,...path,...suffix]);
  const out={...layout,edges:layout.edges.map(e=>String(e.id)===String(edgeId)
    ?{...e,sections:[{startPoint:full[0],bendPoints:full.slice(1,-1),endPoint:full.at(-1)}]}
    :e)};
  return out;
}

export function routeFixedPorts(layout){
  if(!(layout.edges?.length))return layout;
  const nodes=new Map(layout.children.map(n=>[n.id,n]));
  const edges=layout.edges.filter(e=>e.sections?.length===1);
  if(edges.length!==layout.edges.length)return null;
  const step=10,pad=180;
  const minX=Math.floor((Math.min(...layout.children.map(n=>n.x))-pad)/step)*step;
  const minY=Math.floor((Math.min(...layout.children.map(n=>n.y))-pad)/step)*step;
  const width=Math.ceil((Math.max(...layout.children.map(n=>n.x+n.width))-minX+pad)/step)+1;
  const height=Math.ceil((Math.max(...layout.children.map(n=>n.y+n.height))-minY+pad)/step)+1;
  if(width*height>500000)return null;
  const xy=p=>[Math.round((p.x-minX)/step),Math.round((p.y-minY)/step)];
  const point=cell=>({x:minX+(cell%width)*step,y:minY+Math.floor(cell/width)*step});
  const cell=p=>{const [x,y]=xy(p);return y*width+x;};
  const blocked=new Uint8Array(width*height);
  for(const n of layout.children){const [a,b]=xy({x:n.x-10,y:n.y-10}),[c,d]=xy({x:n.x+n.width+10,y:n.y+n.height+10});
    for(let y=Math.max(0,b);y<=Math.min(height-1,d);y++)for(let x=Math.max(0,a);x<=Math.min(width-1,c);x++)blocked[y*width+x]=1;
  }
  const endpoints=edges.map(e=>{
    const s=e.sections[0],source=nodes.get(e.sources[0].replace(/:(?:in|out):\d+$/,"")),target=nodes.get(e.targets[0].replace(/:(?:in|out):\d+$/,""));
    if(!source||!target)return null;
    const start={x:minX+Math.ceil((source.x+source.width+30-minX)/step)*step,y:s.startPoint.y};
    const end={x:minX+Math.floor((target.x-30-minX)/step)*step,y:s.endPoint.y};
    return {edge:e,owner:e.sources[0],start:cell(start),end:cell(end),
      prefix:[s.startPoint,start,point(cell(start))],suffix:[point(cell(end)),end,s.endPoint]};
  });
  if(endpoints.some(e=>!e))return null;
  const fanout=new Map();for(const e of endpoints)fanout.set(e.owner,(fanout.get(e.owner)||0)+1);
  const orders=[endpoints,[...endpoints].reverse(),
    [...endpoints].sort((a,b)=>distance(b)-distance(a)),[...endpoints].sort((a,b)=>distance(a)-distance(b)),
    [...endpoints].sort((a,b)=>point(a.end).y-point(b.end).y),[...endpoints].sort((a,b)=>point(b.end).y-point(a.end).y),
    [...endpoints].sort((a,b)=>fanout.get(a.owner)-fanout.get(b.owner)||point(a.end).y-point(b.end).y),
    [...endpoints].sort((a,b)=>fanout.get(b.owner)-fanout.get(a.owner)||point(a.end).y-point(b.end).y)];
  function distance(e){const a=point(e.start),b=point(e.end);return Math.abs(a.x-b.x)+Math.abs(a.y-b.y);}
  function reserveLine(occupied,a,b,owner){
    const [x1,y1]=xy(a),[x2,y2]=xy(b);let x=x1,y=y1;
    while(true){const id=y*width+x,existing=occupied.get(id);if(existing&&existing!==owner)return false;occupied.set(id,owner);
      if(x!==x2)x+=Math.sign(x2-x);else if(y!==y2)y+=Math.sign(y2-y);else break;
    }return true;
  }
  for(const order of orders){
    const occupied=new Map();let valid=true;
    for(const e of endpoints)for(const path of [e.prefix,e.suffix])for(let i=1;i<path.length;i++)
      if(!reserveLine(occupied,path[i-1],path[i],e.owner))valid=false;
    if(!valid)continue;
    const paths=new Map();
    for(const e of order){
      const heap=new Heap(),cost=new Map(),parents=new Map(),end=point(e.end);
      const initial=e.start*4;heap.push({id:initial,score:0,g:0});cost.set(initial,0);let found;
      while(heap.items.length){const current=heap.pop();if(current.g!==cost.get(current.id))continue;
        const at=Math.floor(current.id/4),dir=current.id%4;if(at===e.end){found=current.id;break;}
        const x=at%width,y=Math.floor(at/width);
        for(const [dx,dy,nextDir] of [[1,0,0],[0,1,1],[-1,0,2],[0,-1,3]]){
          const nx=x+dx,ny=y+dy;if(nx<0||nx>=width||ny<0||ny>=height)continue;
          const next=ny*width+nx,owner=occupied.get(next);
          if(blocked[next]||owner&&owner!==e.owner)continue;
          const reuse=owner===e.owner;
          const id=next*4+nextDir,g=current.g+(reuse ? 0.2 : 1)+(dir===nextDir?0:.35);
          if(g>=(cost.get(id)??Infinity))continue;
          cost.set(id,g);parents.set(id,current.id);const p=point(next);
          heap.push({id,g,score:g+(Math.abs(p.x-end.x)+Math.abs(p.y-end.y))/step});
        }
      }
      if(found===undefined){valid=false;break;}
      const path=[];for(let id=found;id!==undefined;id=parents.get(id))path.push(point(Math.floor(id/4)));path.reverse();
      const full=simplify([...e.prefix,...path,...e.suffix]);
      for(let i=1;i<full.length;i++)if(!reserveLine(occupied,full[i-1],full[i],e.owner))valid=false;
      if(!valid)break;paths.set(e.edge.id,full);
    }
    if(valid)return {...layout,edges:layout.edges.map(e=>{const p=paths.get(e.id);return {...e,sections:[{startPoint:p[0],bendPoints:p.slice(1,-1),endPoint:p.at(-1)}]};})};
  }
  return null;
}
