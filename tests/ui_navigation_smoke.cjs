// Isolated Chrome + Vite smoke test. All API/image data is synthetic and intercepted.
const {spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),net=require('node:net')
const {cleanup}=require('./smoke_profile.cjs')
const root=path.resolve(__dirname,'..'),tag=process.argv[2]||'check'
if(!/^[a-zA-Z0-9_-]+$/.test(tag))throw Error('Invalid smoke run tag')
const baseDir=path.join(root,'logs/ui_smoke');fs.mkdirSync(baseDir,{recursive:true})
const out=fs.mkdtempSync(path.join(baseDir,tag+'_'+Date.now()+'_'))
const sleep=ms=>new Promise(r=>setTimeout(r,ms))
async function port(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p}
async function until(fn,attempts=120){for(let i=0;i<attempts;i++){try{const v=await fn();if(v)return v}catch{}await sleep(100)}throw Error('Timed out waiting for UI')}
async function cdp(url){const ws=new WebSocket(url);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let id=0;const pending=new Map(),events=[];ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);if(!p)return;pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}else for(const fn of events)fn(m)});return {call(method,params={}){return new Promise((resolve,reject)=>{const n=++id;const timer=setTimeout(()=>{pending.delete(n);reject(Error('CDP timeout: '+method))},15000);pending.set(n,{resolve:v=>{clearTimeout(timer);resolve(v)},reject:e=>{clearTimeout(timer);reject(e)}});ws.send(JSON.stringify({id:n,method,params}))})},on(fn){events.push(fn)},close(){ws.close()}}}
;(async()=>{let vite,browser,dev,finishing;const failures=[]
 const finish=()=>finishing??=(async()=>{
  if(!fs.existsSync(path.join(out,'report.json')))fs.writeFileSync(path.join(out,'report.json'),JSON.stringify({status:fs.existsSync(path.join(out,'error.log'))?'failed':'success',errors:failures},null,2))
  const result=await cleanup({root,out,profile:path.join(out,'profile'),browser,close:async()=>{if(dev)await dev.call('Browser.close').catch(()=>{})}})
  if(result.status!=='removed')console.error('Profile retained:',result.reason)
  if(dev)dev.close();if(vite&&!vite.killed)vite.kill()
 })()
 const interrupted=signal=>{fs.writeFileSync(path.join(out,'error.log'),'Interrupted: '+signal);finish().finally(()=>process.exit(signal==='SIGINT'?130:signal==='SIGTERM'?143:1))}
 const onInt=()=>interrupted('SIGINT'),onTerm=()=>interrupted('SIGTERM')
 const onError=e=>interrupted('uncaughtException: '+String(e.stack||e)),onReject=e=>interrupted('unhandledRejection: '+String(e?.stack||e))
 process.once('SIGINT',onInt);process.once('SIGTERM',onTerm);process.once('uncaughtException',onError);process.once('unhandledRejection',onReject)
 try{
  const vp=await port(),dp=await port(),base=`http://127.0.0.1:${vp}`
  vite=spawn(process.execPath,[path.join(root,'frontend/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',String(vp),'--strictPort'],{cwd:path.join(root,'frontend'),windowsHide:true,stdio:'ignore'})
  await until(async()=> (await fetch(base)).ok)
  const chrome=process.env.TOOLBOX_CHROME||path.join(process.env.ProgramFiles,'Google/Chrome/Application/chrome.exe')
  const chromeLog=fs.openSync(path.join(out,'chrome.log'),'a')
  try{browser=spawn(chrome,['--headless=new','--disable-gpu','--no-first-run','--no-default-browser-check','--disable-extensions',`--remote-debugging-port=${dp}`,'--remote-debugging-address=127.0.0.1',`--user-data-dir=${path.join(out,'profile')}`,'about:blank'],{windowsHide:true,stdio:['ignore',chromeLog,chromeLog]})}finally{fs.closeSync(chromeLog)}
  fs.writeFileSync(path.join(out,'processes.json'),JSON.stringify({vite: vite.pid,browser:browser.pid,vitePort:vp,debugPort:dp,profile:path.join(out,'profile')}))
  await until(async()=> (await fetch(`http://127.0.0.1:${dp}/json/version`,{signal:AbortSignal.timeout(1000)})).ok,300)
  const target=await (await fetch(`http://127.0.0.1:${dp}/json/new?about:blank`,{method:'PUT'})).json();dev=await cdp(target.webSocketDebuggerUrl)
  const requests=[],cached=new Set(),read=new Set();let listRequests=0,popularRequests=0
  const imageAttempts=new Map();const imageChecks={}
  let syncState={status:'idle'},syncPosts=0,autoReads=0,startupPosts=0,autoLast=null
  const unfollowed=new Set()
  const item=i=>({source:'gamebanana',item_type:'Mod',item_id:i,game_id:8552,game_name:'Genshin Impact',title:`Fixture ${i}`,author_id:7,author_name:'Fixture Author',author_url:'https://gamebanana.com/members/7',original_url:`https://gamebanana.com/mods/${i}`,created_at:'2026-10-01T00:00:00Z',updated_at:null,first_seen_at:'2026-10-20T00:00:00Z',version:null,content_rating_status:'UNKNOWN',source_ratings:{codes:['UNKNOWN'],verification:'unverified_labels'},is_read:read.has(i),image_count:tag==='density'&&i===2?0:6,preview_urls:tag==='density'&&i===2?[]:[`${base}/fixture/cover/${i}.svg`],preview_images:tag==='density'&&i===2?[]:Array.from({length:6},(_,n)=>({image_url:`${base}/fixture/full/${i}/${n}.svg`,thumbnail_url:`${base}/fixture/cover/${i}.svg`,switch_url:`${base}/fixture/switch/${i}/${n}.svg`}))})
  dev.on(async m=>{if(m.method==='Network.requestWillBeSent'&&m.params.type==='Image')requests.push({id:m.params.requestId,url:m.params.request.url});if(m.method==='Network.requestServedFromCache')cached.add(m.params.requestId)
    if(m.method==='Runtime.exceptionThrown')failures.push(m.params.exceptionDetails.text)
    if(m.method!=='Fetch.requestPaused')return;const p=m.params,u=new URL(p.request.url);let value,status=200,headers=[{name:'Content-Type',value:'application/json'}]
    if(u.pathname.startsWith('/fixture/')){const attempt=(imageAttempts.get(u.pathname)||0)+1;imageAttempts.set(u.pathname,attempt);if(tag==='ob2b'&&attempt===1&&['/fixture/cover/12.svg','/fixture/full/12/2.svg','/fixture/switch/12/4.svg'].includes(u.pathname))status=503;await sleep(u.pathname.includes('/full/')?250:90);value=`<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><rect width="1600" height="1000" fill="#b8b0d9"/></svg>`;headers=[{name:'Content-Type',value:'image/svg+xml'},{name:'Cache-Control',value:status===200?'public, max-age=3600':'no-store'}]}
    else if(u.pathname==='/api/games')value={games:[{game_id:8552,name:'Genshin Impact'},{game_id:18366,name:'Honkai Star Rail'}]}
    else if(u.pathname==='/api/content-ratings')value={options:[{_sAlias:'UNKNOWN',_sTitle:'UNKNOWN'}]}
    else if(u.pathname==='/api/mods'){listRequests++;let rows=Array.from({length:72},(_,i)=>item(i+1));if(u.searchParams.get('game')==='18366')rows=[];if(u.searchParams.get('exclude_id'))rows=rows.filter(r=>r.item_id!==Number(u.searchParams.get('exclude_id')));if(u.searchParams.get('read')==='unread')rows=rows.filter(r=>!r.is_read);if(u.searchParams.get('read')==='read')rows=rows.filter(r=>r.is_read);const limit=Number(u.searchParams.get('limit')||25);value={items:rows.slice(Number(u.searchParams.get('offset')),Number(u.searchParams.get('offset'))+limit),total_count:rows.length,limit,offset:0,discovery:{local_count:72,coverage:'unverified',last_sync:null}}}
    else if(u.pathname==='/api/popular'){popularRequests++;await sleep(600);const page=Number(u.searchParams.get('page'));value={items:Array.from({length:20},(_,i)=>({...item((page-1)*20+i+1),is_local:true,rank:(page-1)*20+i+1,metrics:{likes:20-i},ranking_scope:'recent_sample'})),has_more:page<3,fetched_at:'2026-10-30T00:00:00Z',cached:true,coverage:'incomplete',pages_scanned:2,candidate_count:60,missing_metrics:0,errors:[],cutoff:'2026-10-01T00:00:00Z'}}
    else if(u.pathname==='/api/mod'){value=item(Number(u.searchParams.get('item_id')));value.preview_urls=value.preview_images.map(i=>i.image_url)}
    else if(u.pathname==='/api/sync'){if(p.request.method==='POST'){syncPosts++;syncState={status:'checking'}}value=syncState}
    else if(u.pathname==='/api/auto-sync/startup'){startupPosts++;autoLast={status:'checking',started_at:'2026-11-02T00:00:00Z'};syncState={status:'checking',current_game:'Fixture game',current_page:1};value={status:'requested'}}
    else if(u.pathname==='/api/auto-sync'){autoReads++;value={settings:{mode:tag==='startup'?'check':'off',interval_hours:6,max_pages:3},last_run:autoLast,task:{registered:false},next_due:null}}
    else if(u.pathname==='/api/history-sync')value={settings:{enabled:false,paused:false,max_pages:2},last_run:null,games:[],coverage:'incomplete',not_before:0}
    else if(u.pathname==='/api/authors'||u.pathname==='/api/author'){let rows=Array.from({length:tag==='compact'?16:1},(_,i)=>({source:'gamebanana',author_id:7+i,name:i?'Fixture Author '+i:'Fixture Author',mod_count:72,avatar_url:null})).filter(a=>!unfollowed.has(a.author_id));const followed=rows.length;if(u.searchParams.get('search'))rows=rows.filter(a=>a.name.includes(u.searchParams.get('search')));value={items:rows,total_count:rows.length,followed_count:followed}}
    else if(u.pathname==='/api/subscription'){if(p.request.postData){const body=JSON.parse(p.request.postData);body.followed?unfollowed.delete(body.author_id):unfollowed.add(body.author_id);value={available:true,followed:body.followed}}else value={available:true,followed:tag==='compact'&&!unfollowed.has(Number(u.searchParams.get('author_id')))}}
    else if(u.pathname==='/api/read-state'){const body=p.request.postData?JSON.parse(p.request.postData):null,id=body?.item_id||Number(u.searchParams.get('item_id'));if(body){body.is_read?read.add(id):read.delete(id)}value={available:true,is_read:read.has(id),first_viewed_at:read.has(id)?'2026-10-30T00:00:00Z':null}}
    else value={status:'not_checked'}
    await dev.call('Fetch.fulfillRequest',{requestId:p.requestId,responseCode:status,responseHeaders:headers,body:Buffer.from(status===503?'image temporarily unavailable':typeof value==='string'?value:JSON.stringify(value)).toString('base64')}).catch(e=>{if(!/Invalid InterceptionId|closed|not open|Invalid state/i.test(e.message))failures.push(e.message)})
  })
  await dev.call('Network.enable');await dev.call('Runtime.enable');await dev.call('Page.enable');await dev.call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});await dev.call('Fetch.enable',{patterns:[{urlPattern:'*/api/*'},{urlPattern:'*/fixture/*'}]})
  const evaluate=async expression=>{const result=await dev.call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value}
  await dev.call('Page.navigate',{url:base});await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===25"));await sleep(600)
  const initialImages=requests.length
  if(tag==='density'){
    const click=async text=>evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===${JSON.stringify(text)}).click()`)
    const select=async value=>evaluate(`(()=>{const s=document.querySelector('[aria-label="每页作品数量"]');s.value=${JSON.stringify(String(value))};s.dispatchEvent(new Event('change',{bubbles:true}))})()`)
    const measurements=[]
    if(!await evaluate("document.querySelector('[aria-label=\"每页作品数量\"]').value==='25'&&!!document.querySelector('.compact-grid')"))throw Error('Default must be compact/25')
    if(!await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:2\"] .image-placeholder')?.textContent.includes('暂无')"))throw Error('Missing cover placeholder absent')
    if(requests.some(r=>r.url.includes('/fixture/full/')))throw Error('List loaded gallery originals')
    const beforeModeRequests=listRequests
    for(const mode of ['标准视图','紧凑视图']){
      await click(mode);await sleep(300)
      for(const [width,height] of [[1920,1080],[1366,768]]){
        await dev.call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});await sleep(400)
        const measured=await evaluate(`(()=>{const g=document.querySelector('main .mod-grid'),c=g.querySelector('.mod-card');return {mode:${JSON.stringify(mode)},width:${width},height:${height},columns:getComputedStyle(g).gridTemplateColumns.split(/\\s+/).length,cardHeight:c.getBoundingClientRect().height,overflow:document.documentElement.scrollWidth>innerWidth}})()`)
        if(measured.overflow||mode==='紧凑视图'&&measured.columns!==(width===1920?5:4))throw Error('Density geometry mismatch '+JSON.stringify(measured))
        measurements.push(measured);const shot=await dev.call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,`${mode==='标准视图'?'standard':'compact'}_${width}.png`),Buffer.from(shot.data,'base64'))
      }
    }
    if(listRequests!==beforeModeRequests)throw Error('Density switch queried records again')
    for(const width of [920,700,500]){
      await dev.call('Emulation.setDeviceMetricsOverride',{width,height:900,deviceScaleFactor:1,mobile:false});await sleep(250)
      if(await evaluate('document.documentElement.scrollWidth>innerWidth'))throw Error('Narrow window overflow: '+width)
    }
    await dev.call('Emulation.setDeviceMetricsOverride',{width:1366,height:768,deviceScaleFactor:1,mobile:false})
    await select(15);await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===15"))
    await evaluate("document.querySelector('[aria-label=\"下一页\"]').click()");await until(()=>evaluate("!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:16\"]')"))
    await select(25);await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===25"));if(!await evaluate("!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:16\"]')"))throw Error('Former first record lost')
    await select(50);await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===50"))
    await evaluate("document.querySelector('[aria-label=\"下一页\"]').click()");await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===22"));if(!await evaluate("document.querySelector('[aria-label=\"下一页\"]').disabled"))throw Error('Last page not clamped')
    await select(15);await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===15"));if(!await evaluate("!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:51\"]')"))throw Error('First identity not kept after resize')
    await select(25);await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===25"));await evaluate("document.querySelector('[aria-label=\"下一页\"]').click()");await until(()=>evaluate("!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"]')"))
    await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"]').scrollIntoView({block:'center'})");await sleep(400)
    const top=await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"]').getBoundingClientRect().top")
    await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"] button').click()");await until(()=>evaluate("!!document.querySelector('.gallery-stage')"))
    if(requests.filter(r=>r.url.includes('/fixture/full/60/')).length!==1)throw Error('Gallery preloaded unselected originals')
    await evaluate("document.querySelector('.back-link').click()");await until(()=>evaluate("!location.hash.includes('/mod/')"));await sleep(2400)
    const error=Math.abs(top-await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"]').getBoundingClientRect().top"))
    if(error>3)throw Error('Compact return lost anchor '+error)
    await dev.call('Page.reload');await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===22"))
    if(!await evaluate("document.querySelector('[aria-label=\"每页作品数量\"]').value==='25'&&!!document.querySelector('.compact-grid')"))throw Error('Preferences lost on refresh')
    await click('订阅动态');await until(()=>evaluate("document.querySelectorAll('.compact-card').length===25"))
    await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:10\"] button').click()");await until(()=>evaluate("!!document.querySelector('.detail-meta h2 button')"));await evaluate("document.querySelector('.detail-meta h2 button').click()")
    await until(()=>evaluate("location.hash.includes('/author/')&&document.querySelectorAll('.compact-card').length===25"))
    if(syncPosts||startupPosts||failures.length)throw Error('Unexpected sync or browser error')
    const result={measurements,anchorErrorPx:error,preferencesPersisted:true,pagination:[15,25,50],initialImageAttempts:initialImages,syncPosts,startupPosts,errors:failures}
    fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({out,...result}));await dev.call('Browser.close').catch(()=>{});return
  }
  if(tag==='startup'){
    await until(()=>startupPosts===1)
    if(!await evaluate("document.querySelectorAll('[data-mod-identity]').length===25"))throw Error('Startup blocked local records')
    await evaluate("(()=>{const s=document.querySelector('[aria-label=\"选择游戏\"]');s.value='8552';s.dispatchEvent(new Event('change',{bubbles:true}));document.querySelectorAll('.view-switch')[0].querySelectorAll('button')[1].click()})()")
    await sleep(500)
    for(let i=0;i<2;i++){await evaluate("document.querySelector('[aria-label=\"下一页\"]').click()");await sleep(500)}
    await until(()=>evaluate("!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"]')"))
    await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"]').scrollIntoView({block:'center'})");await sleep(500)
    const before=await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"]').getBoundingClientRect().top")
    const beforeRequests=listRequests
    autoLast={status:'waiting',started_at:'2026-11-02T00:00:00Z',ended_at:'2026-11-02T00:01:00Z',inserted:0,source_updated:0}
    syncState={status:'waiting',game_id:null,token:'preview',report:{inserted:0,updated:0,unchanged:18,skipped:0,source_update_events:0}}
    await until(()=>listRequests>beforeRequests);await sleep(2500)
    const after=await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:60\"]').getBoundingClientRect().top")
    if(Math.abs(before-after)>2)throw Error('Automatic completion lost scroll anchor '+before+' -> '+after)
    if(!await evaluate("document.querySelector('[aria-label=\"选择游戏\"]').value==='8552'&&document.querySelector('.view-switch .selected')?.textContent==='未阅'"))throw Error('Automatic completion reset filters')
    if(startupPosts!==1||syncPosts)throw Error('Startup retriggered or auto-confirmed')
    await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='订阅动态').click()");await sleep(300)
    await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='最新 MOD').click()");await sleep(500)
    if(startupPosts!==1)throw Error('Navigation retriggered startup')
    const report={startupPosts,syncPosts,localFirstPaint:true,listRefreshed:true,filtersPreserved:true,anchorErrorPx:Math.abs(before-after),errors:failures}
    if(failures.length)throw Error(JSON.stringify(failures));fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));console.log(JSON.stringify({out,...report}));await dev.call('Browser.close').catch(()=>{});return
  }
  if(tag==='compact'){
    const click=async text=>evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===${JSON.stringify(text)}).click()`)
    if(!await evaluate("document.querySelector('#sync-management').hidden"))throw Error('Sync should default collapsed')
    const reads=autoReads
    await click('展开详情');await click('收起详情');await click('展开详情')
    if(syncPosts||autoReads!==reads)throw Error('Disclosure caused a task or refetch')
    if(!await evaluate("!!document.querySelector('[aria-label=\"自动同步模式\"]')"))throw Error('Settings missing')
    await click('收起详情');await click('立即检查');await until(()=>evaluate("document.querySelector('.sync-summary').textContent.includes('正在检查')"))
    await click('展开详情');await click('收起详情');if(syncPosts!==1)throw Error('Running task restarted')
    syncState={status:'waiting',token:'fixture',game_id:null};await until(()=>evaluate("document.querySelector('.sync-summary').textContent.includes('待确认')"))
    if(syncPosts!==1)throw Error('Preview auto-confirmed')
    await click('展开详情');if(!await evaluate("Array.from(document.querySelectorAll('button')).some(b=>b.textContent.includes('确认导入'))"))throw Error('Confirmation missing');await click('收起详情')
    syncState={status:'failed',error:'fixture timeout'};await until(()=>evaluate("document.querySelector('.sync-summary').textContent.includes('失败')"))
    await dev.call('Page.reload');await until(()=>evaluate("document.querySelector('.sync-summary')?.textContent.includes('失败')"));if(syncPosts!==1||!await evaluate("document.querySelector('#sync-management').hidden"))throw Error('Reload restarted task or lost disclosure default')
    await evaluate("document.querySelector('[aria-controls=\"rating-options\"]').click()")
    await evaluate("document.querySelector('#rating-options input').click()")
    await evaluate("document.querySelector('[aria-controls=\"rating-options\"]').click()")
    if(!await evaluate("document.querySelector('[aria-controls=\"rating-options\"]').textContent.includes('已选 0')"))throw Error('Hidden ratings reset')
    await evaluate("document.querySelector('[aria-controls=\"rating-options\"]').focus()")
    await dev.call('Input.dispatchKeyEvent',{type:'keyDown',key:' ',code:'Space',windowsVirtualKeyCode:32});await dev.call('Input.dispatchKeyEvent',{type:'keyUp',key:' ',code:'Space',windowsVirtualKeyCode:32})
    await until(()=>evaluate("document.querySelector('[aria-controls=\"rating-options\"]').getAttribute('aria-expanded')==='true'"));await click('全选')
    await click('订阅动态');await until(()=>evaluate("Array.from(document.querySelectorAll('button')).some(b=>b.textContent.includes('我的关注（16）'))"))
    await click('我的关注（16）');await until(()=>evaluate("document.querySelectorAll('.author-card').length===16"))
    await evaluate("(()=>{const i=document.querySelector('[aria-label=\"搜索关注作者\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,'Fixture Author 15');i.dispatchEvent(new Event('input',{bubbles:true}))})()");await until(()=>evaluate("document.querySelectorAll('.author-card').length===1"))
    await evaluate("(()=>{const i=document.querySelector('[aria-label=\"搜索关注作者\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(i,'');i.dispatchEvent(new Event('input',{bubbles:true}))})()");await until(()=>evaluate("document.querySelectorAll('.author-card').length===16"))
    const shot=await dev.call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'authors.png'),Buffer.from(shot.data,'base64'))
    await evaluate("document.querySelector('.author-secondary summary').click()");await until(()=>evaluate("document.querySelector('.author-secondary button')?.textContent.includes('取消关注')"));await evaluate("document.querySelector('.author-secondary button').click()");await until(()=>evaluate("document.querySelectorAll('.author-card').length===15"))
    await click('最新 MOD');await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===25"));await evaluate("document.querySelector('[data-mod-identity] button').click()");await until(()=>evaluate("document.querySelectorAll('.related-item').length===4"));await evaluate("document.querySelector('.related-item').click()");await until(()=>evaluate("location.hash.endsWith('/2')"))
    const detailShot=await dev.call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,'related.png'),Buffer.from(detailShot.data,'base64'))
    if(failures.length)throw Error(JSON.stringify(failures))
    console.log(JSON.stringify({out,syncPosts,disclosurePreservedState:true,ratingKeyboardAndSelection:true,authors:16,errors:failures}));await dev.call('Browser.close').catch(()=>{});return
  }
  if(tag.startsWith('visual_')){
    const measurements=[]
    for(const [width,height] of [[1920,1080],[1366,768]]){
      await dev.call('Emulation.setDeviceMetricsOverride',{width,height,deviceScaleFactor:1,mobile:false});await sleep(600)
      measurements.push(await evaluate(`({width:${width},height:${height},overflow:document.documentElement.scrollWidth>innerWidth,syncHeight:document.querySelector('main section')?.getBoundingClientRect().height,firstCardTop:document.querySelector('[data-mod-identity]')?.getBoundingClientRect().top,visibleCards:Array.from(document.querySelectorAll('[data-mod-identity]')).filter(e=>e.getBoundingClientRect().top<innerHeight).length})`))
      const shot=await dev.call('Page.captureScreenshot',{format:'png'});fs.writeFileSync(path.join(out,`${width}x${height}.png`),Buffer.from(shot.data,'base64'))
    }
    fs.writeFileSync(path.join(out,'measurements.json'),JSON.stringify(measurements,null,2));console.log(JSON.stringify({out,measurements}));await dev.call('Browser.close').catch(()=>{});return
  }
  await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:12\"]').scrollIntoView({block:'center'})");await sleep(500)
  if(tag==='ob2b'){await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='重试预览图').click()");await until(()=>evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:12\"] img')?.naturalWidth>0"));imageChecks.coverRetry=true}
  const before=await evaluate("({y:scrollY,top:document.querySelector('[data-mod-identity=\"gamebanana:Mod:12\"]').getBoundingClientRect().top})")
  await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:12\"] button').click()")
  await until(()=>evaluate("!!document.querySelector('.gallery-stage')"));await sleep(700)
  if(tag==='ob2b'){
    imageChecks.originalsBeforeSwitch=requests.filter(r=>r.url.includes('/fixture/full/12/')).length
    if(imageChecks.originalsBeforeSwitch!==1)throw Error('Gallery preloaded unselected originals')
    await evaluate("document.querySelector('[aria-label=\"重试第 5 张缩略图\"]').click()");await sleep(400);imageChecks.thumbnailRetry=true
    for(let index=0;index<6;index++){
      await evaluate(`document.querySelectorAll('.gallery-thumb')[${index}].click()`);await sleep(400)
      if(index===2){await evaluate("Array.from(document.querySelectorAll('button')).find(b=>b.textContent==='重试高清图片').click()");imageChecks.originalRetry=true}
      await until(()=>evaluate(`document.querySelector('.gallery-stage img')?.src.endsWith('/12/${index}.svg')&&document.querySelector('.gallery-stage img')?.naturalWidth>0`))
    }
    imageChecks.sixOriginalsViewed=true
  }
  const beforeReturn=requests.length,apiBeforeReturn=listRequests
  await evaluate("document.querySelector('.back-link').click()")
  await until(()=>evaluate("!location.hash.includes('/mod/')"));await sleep(2000)
  const after=await evaluate("({y:scrollY,top:document.querySelector('[data-mod-identity=\"gamebanana:Mod:12\"]').getBoundingClientRect().top})")
  const result={fixture:'72 synthetic local MODs, delayed SVGs + 600ms ranking responses; no production API/images',initialImageAttempts:initialImages,before,after,anchorErrorPx:Math.abs(before.top-after.top),returnImageAttempts:requests.length-beforeReturn,returnListRequests:listRequests-apiBeforeReturn,cacheServed:cached.size,errors:failures}
  result.imageChecks=imageChecks
  if(tag==='ob2b'&&result.returnImageAttempts!==0)throw Error('Returning to list requested images again')
  await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:12\"] button').click()")
  await until(()=>evaluate("location.hash.includes('/mod/')"));await evaluate('history.back()');await until(()=>evaluate("!location.hash.includes('/mod/')"));await sleep(700)
  result.browserBackTop=await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:12\"]').getBoundingClientRect().top")
  await evaluate('history.forward()');await until(()=>evaluate("location.hash.includes('/mod/')"));await until(()=>evaluate("!!document.querySelector('.gallery-stage')"));result.forwardOpenedDetail=true
  await evaluate('history.back()');await until(()=>evaluate("!location.hash.includes('/mod/')"));await sleep(700)
  result.forwardBackTop=await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:12\"]').getBoundingClientRect().top")
  await evaluate("document.querySelector('[aria-label=\"选择游戏\"]').value='18366';document.querySelector('[aria-label=\"选择游戏\"]').dispatchEvent(new Event('change',{bubbles:true}))")
  await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===0"));await sleep(300);result.gameSwitchY=await evaluate('scrollY')
  await evaluate("document.querySelector('[aria-label=\"选择游戏\"]').value='8552';document.querySelector('[aria-label=\"选择游戏\"]').dispatchEvent(new Event('change',{bubbles:true}))")
  await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===25"))
  await evaluate("const input=document.querySelector('[aria-label=\"搜索 MOD ID、标题或作者\"]');Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input,'Fixture');input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('form').requestSubmit()")
  await evaluate("document.querySelector('[aria-label=\"作品排序\"]').value='first_seen';document.querySelector('[aria-label=\"作品排序\"]').dispatchEvent(new Event('change',{bubbles:true}))")
  await sleep(300);await evaluate("document.querySelector('[aria-label=\"下一页\"]').click()")
  await until(()=>evaluate("!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:30\"]')"))
  await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:30\"]').scrollIntoView({block:'center'});document.querySelector('[data-mod-identity=\"gamebanana:Mod:30\"] button').click()")
  await until(()=>evaluate("!!document.querySelector('.gallery-stage')"));await sleep(400);await evaluate("document.querySelector('.back-link').click()")
  await until(()=>evaluate("!location.hash.includes('/mod/')"));await sleep(600)
  result.restoredFilters=await evaluate("({game:document.querySelector('[aria-label=\"选择游戏\"]').value,search:document.querySelector('[aria-label=\"搜索 MOD ID、标题或作者\"]').value,sort:document.querySelector('[aria-label=\"作品排序\"]').value,hasPageTwoMod:!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:30\"]')})")
  if(tag!=='before'&&(result.restoredFilters.game!=='8552'||result.restoredFilters.search!=='Fixture'||result.restoredFilters.sort!=='first_seen'||!result.restoredFilters.hasPageTwoMod))throw Error('Filter/page restoration failed')
  if(tag!=='before'&&(result.anchorErrorPx>3||Math.abs(result.browserBackTop-before.top)>3||Math.abs(result.forwardBackTop-before.top)>3||result.gameSwitchY>3||failures.length))throw Error('Navigation/console assertions failed: '+JSON.stringify(result))
  // Required OB2-A cases: page three, subscriptions, and ranking query after reload.
  const clickText=async text=>evaluate(`Array.from(document.querySelectorAll('button')).find(b=>b.textContent.trim()===${JSON.stringify(text)}).click()`)
  const select=async(label,value)=>evaluate(`document.querySelector('[aria-label="${label}"]').value=${JSON.stringify(value)};document.querySelector('[aria-label="${label}"]').dispatchEvent(new Event('change',{bubbles:true}))`)
  const roundTrip=async(id,reload=false)=>{
    await until(()=>evaluate(`!!document.querySelector('[data-mod-identity="gamebanana:Mod:${id}"]')`));await sleep(400)
    await evaluate(`document.querySelector('[data-mod-identity="gamebanana:Mod:${id}"]').scrollIntoView({block:'center'})`);await sleep(500)
    const saved=await evaluate(`document.querySelector('[data-mod-identity="gamebanana:Mod:${id}"]').getBoundingClientRect().top`)
    await evaluate(`document.querySelector('[data-mod-identity="gamebanana:Mod:${id}"] button').click()`)
    await until(()=>evaluate("!!document.querySelector('.gallery-stage')"));await sleep(300)
    if(reload){await dev.call('Page.reload');await until(()=>evaluate("!!document.querySelector('.gallery-stage')"));await sleep(400)}
    const count=popularRequests
    await evaluate("document.querySelector('.back-link').click()")
    await until(()=>evaluate("!location.hash.includes('/mod/')"));await until(()=>evaluate(`!!document.querySelector('[data-mod-identity="gamebanana:Mod:${id}"]')`));await sleep(2600)
    const top=await evaluate(`document.querySelector('[data-mod-identity="gamebanana:Mod:${id}"]').getBoundingClientRect().top`)
    if(Math.abs(saved-top)>3)throw Error(`Anchor ${id}: ${saved} -> ${top}`)
    return {anchorErrorPx:Math.abs(saved-top),rankingRequestsOnReturn:popularRequests-count}
  }
  await clickText('已有图片')
  // Rating checkboxes use their enclosing text label rather than aria-label.
  await evaluate("(()=>{const label=Array.from(document.querySelectorAll('aside label')).find(e=>e.textContent.trim()==='UNKNOWN');if(label){const box=label.querySelector('input');if(box.checked)box.click()}})()")
  await sleep(100)
  await evaluate("(()=>{const label=Array.from(document.querySelectorAll('aside label')).find(e=>e.textContent.trim()==='UNKNOWN');if(label&&!label.querySelector('input').checked)label.querySelector('input').click()})()")
  await sleep(300)
  await evaluate("document.querySelector('[aria-label=\"下一页\"]').click()")
  await until(()=>evaluate("!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:30\"]')"))
  await evaluate("document.querySelector('[aria-label=\"下一页\"]').click()")
  result.latestThirdPage=await roundTrip(60)
  result.latestPageSaved=await evaluate('history.state.eryouView.page')
  result.savedImageFilter=await evaluate('history.state.eryouView.withImages')
  result.savedRatings=await evaluate('history.state.eryouView.ratings')
  if(!result.savedImageFilter||JSON.stringify(result.savedRatings)!=='["UNKNOWN"]')throw Error('Image/rating filter lost')
  if(result.latestPageSaved!==2)throw Error('Third-page index not preserved')
  await clickText('订阅动态');await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===25"))
  result.subscriptions=await roundTrip(10)
  result.subscriptionFeed=await evaluate('history.state.eryouView.feed')
  if(result.subscriptionFeed!=='subscriptions')throw Error('Subscription section lost')
  // Marked state already exists from mock auto-read; keep the read filter on return.
  await evaluate("Array.from(document.querySelector('[aria-label=\"已阅筛选\"]').querySelectorAll('button')).find(b=>b.textContent==='已阅').click()")
  await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length>0&&document.querySelectorAll('[data-mod-identity]').length<25"))
  result.readFilter=await roundTrip(10)
  if(await evaluate('history.state.eryouView.readFilter')!=='read')throw Error('Read filter lost')
  await clickText('热门 MOD');await select('近期时间窗口','7');await select('热门排序','views')
  await until(()=>evaluate("document.querySelector('[data-ranking-ready=\"true\"]')!==null"));await clickText('下一页')
  await until(()=>evaluate("!!document.querySelector('[data-mod-identity=\"gamebanana:Mod:30\"]')"))
  result.popularReturn=await roundTrip(30)
  if(result.popularReturn.rankingRequestsOnReturn!==0)throw Error('Unnecessary ranking refetch on normal return')
  result.popularReload=await roundTrip(30,true)
  const popular=await evaluate('history.state.eryouView.popular')
  result.popularState=popular
  if(popular.days!==7||popular.sort!=='views'||popular.groups['8552'].page!==2)throw Error('Ranking query lost after reload')
  if(tag==='ob5b'){
    await clickText('最新 MOD');await evaluate("Array.from(document.querySelector('[aria-label=\"已阅筛选\"]').querySelectorAll('button')).find(b=>b.textContent==='全部').click()");await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===25"));
    await evaluate("document.querySelector('[data-mod-identity=\"gamebanana:Mod:1\"] button').click()");await until(()=>evaluate("!!document.querySelector('.detail-meta h2 button')"));
    await evaluate("document.querySelector('.detail-meta h2 button').click()");await until(()=>evaluate("location.hash.includes('/author/')&&document.querySelectorAll('[data-mod-identity]').length===25"));
    result.authorReturn=await roundTrip(12);result.savedAuthor=await evaluate('history.state.eryouView.author');
    if(result.savedAuthor.author_id!==7||result.authorReturn.anchorErrorPx>3)throw Error('Author identity or position lost');
  }
  if(failures.length)throw Error('Browser exceptions: '+JSON.stringify(failures))
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({...result,report:path.join(out,'report.json')},null,2))
  await dev.call('Browser.close').catch(()=>{})
}catch(e){fs.writeFileSync(path.join(out,'error.log'),String(e.stack||e));throw e}finally{
 await finish();process.removeListener('SIGINT',onInt);process.removeListener('SIGTERM',onTerm);process.removeListener('uncaughtException',onError);process.removeListener('unhandledRejection',onReject)
}})().catch(e=>{console.error(e);process.exitCode=1})
