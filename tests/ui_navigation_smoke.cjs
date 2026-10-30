// Isolated Chrome + Vite smoke test. All API/image data is synthetic and intercepted.
const {spawn}=require('node:child_process'),fs=require('node:fs'),path=require('node:path'),net=require('node:net')
const root=path.resolve(__dirname,'..'),tag=process.argv[2]||'check',out=path.join(root,'logs','ui_smoke',tag+'_'+Date.now());fs.mkdirSync(out,{recursive:true})
const sleep=ms=>new Promise(r=>setTimeout(r,ms))
async function port(){const s=net.createServer();await new Promise(r=>s.listen(0,'127.0.0.1',r));const p=s.address().port;await new Promise(r=>s.close(r));return p}
async function until(fn){for(let i=0;i<120;i++){try{const v=await fn();if(v)return v}catch{}await sleep(100)}throw Error('Timed out waiting for UI')}
async function cdp(url){const ws=new WebSocket(url);await new Promise(r=>ws.addEventListener('open',r,{once:true}));let id=0;const pending=new Map(),events=[];ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id){const p=pending.get(m.id);pending.delete(m.id);m.error?p.reject(Error(m.error.message)):p.resolve(m.result)}else for(const fn of events)fn(m)});return {call(method,params={}){return new Promise((resolve,reject)=>{const n=++id;pending.set(n,{resolve,reject});ws.send(JSON.stringify({id:n,method,params}))})},on(fn){events.push(fn)},close(){ws.close()}}}
;(async()=>{let vite,browser,dev;const failures=[];try{
  const vp=await port(),dp=await port(),base=`http://127.0.0.1:${vp}`
  vite=spawn(process.execPath,[path.join(root,'frontend/node_modules/vite/bin/vite.js'),'--host','127.0.0.1','--port',String(vp),'--strictPort'],{cwd:path.join(root,'frontend'),windowsHide:true,stdio:'ignore'})
  await until(async()=> (await fetch(base)).ok)
  const chrome=process.env.TOOLBOX_CHROME||path.join(process.env.ProgramFiles,'Google/Chrome/Application/chrome.exe')
  browser=spawn(chrome,['--headless=new','--no-first-run','--no-default-browser-check','--disable-extensions',`--remote-debugging-port=${dp}`,'--remote-debugging-address=127.0.0.1',`--user-data-dir=${path.join(out,'profile')}`,'about:blank'],{windowsHide:true,stdio:'ignore'})
  fs.writeFileSync(path.join(out,'processes.json'),JSON.stringify({vite: vite.pid,browser:browser.pid,vitePort:vp,debugPort:dp,profile:path.join(out,'profile')}))
  await until(async()=> (await fetch(`http://127.0.0.1:${dp}/json/version`)).ok)
  const target=await (await fetch(`http://127.0.0.1:${dp}/json/new?about:blank`,{method:'PUT'})).json();dev=await cdp(target.webSocketDebuggerUrl)
  const requests=[],cached=new Set(),read=new Set();let listRequests=0,popularRequests=0
  const imageAttempts=new Map();const imageChecks={}
  const item=i=>({source:'gamebanana',item_type:'Mod',item_id:i,game_id:8552,game_name:'Genshin Impact',title:`Fixture ${i}`,author_id:7,author_name:'Fixture Author',author_url:'https://gamebanana.com/members/7',original_url:`https://gamebanana.com/mods/${i}`,created_at:'2026-10-01T00:00:00Z',updated_at:null,first_seen_at:'2026-10-20T00:00:00Z',version:null,content_rating_status:'UNKNOWN',source_ratings:{codes:['UNKNOWN'],verification:'unverified_labels'},is_read:read.has(i),image_count:6,preview_urls:[`${base}/fixture/cover/${i}.svg`],preview_images:Array.from({length:6},(_,n)=>({image_url:`${base}/fixture/full/${i}/${n}.svg`,thumbnail_url:`${base}/fixture/cover/${i}.svg`,switch_url:`${base}/fixture/switch/${i}/${n}.svg`}))})
  dev.on(async m=>{if(m.method==='Network.requestWillBeSent'&&m.params.type==='Image')requests.push({id:m.params.requestId,url:m.params.request.url});if(m.method==='Network.requestServedFromCache')cached.add(m.params.requestId)
    if(m.method==='Runtime.exceptionThrown')failures.push(m.params.exceptionDetails.text)
    if(m.method!=='Fetch.requestPaused')return;const p=m.params,u=new URL(p.request.url);let value,status=200,headers=[{name:'Content-Type',value:'application/json'}]
    if(u.pathname.startsWith('/fixture/')){const attempt=(imageAttempts.get(u.pathname)||0)+1;imageAttempts.set(u.pathname,attempt);if(tag==='ob2b'&&attempt===1&&['/fixture/cover/12.svg','/fixture/full/12/2.svg','/fixture/switch/12/4.svg'].includes(u.pathname))status=503;await sleep(u.pathname.includes('/full/')?250:90);value=`<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000"><rect width="1600" height="1000" fill="#b8b0d9"/></svg>`;headers=[{name:'Content-Type',value:'image/svg+xml'},{name:'Cache-Control',value:status===200?'public, max-age=3600':'no-store'}]}
    else if(u.pathname==='/api/games')value={games:[{game_id:8552,name:'Genshin Impact'},{game_id:18366,name:'Honkai Star Rail'}]}
    else if(u.pathname==='/api/content-ratings')value={options:[{_sAlias:'UNKNOWN',_sTitle:'UNKNOWN'}]}
    else if(u.pathname==='/api/mods'){listRequests++;let rows=Array.from({length:72},(_,i)=>item(i+1));if(u.searchParams.get('game')==='18366')rows=[];if(u.searchParams.get('read')==='unread')rows=rows.filter(r=>!r.is_read);if(u.searchParams.get('read')==='read')rows=rows.filter(r=>r.is_read);value={items:rows.slice(Number(u.searchParams.get('offset')),Number(u.searchParams.get('offset'))+18),total_count:rows.length,limit:18,offset:0,discovery:{local_count:72,coverage:'unverified',last_sync:null}}}
    else if(u.pathname==='/api/popular'){popularRequests++;await sleep(600);const page=Number(u.searchParams.get('page'));value={items:Array.from({length:20},(_,i)=>({...item((page-1)*20+i+1),is_local:true,rank:(page-1)*20+i+1,metrics:{likes:20-i},ranking_scope:'recent_sample'})),has_more:page<3,fetched_at:'2026-10-30T00:00:00Z',cached:true,coverage:'incomplete',pages_scanned:2,candidate_count:60,missing_metrics:0,errors:[],cutoff:'2026-10-01T00:00:00Z'}}
    else if(u.pathname==='/api/mod'){value=item(Number(u.searchParams.get('item_id')));value.preview_urls=value.preview_images.map(i=>i.image_url)}
    else if(u.pathname==='/api/subscription')value={available:true,followed:false}
    else if(u.pathname==='/api/read-state'){const body=p.request.postData?JSON.parse(p.request.postData):null,id=body?.item_id||Number(u.searchParams.get('item_id'));if(body){body.is_read?read.add(id):read.delete(id)}value={available:true,is_read:read.has(id),first_viewed_at:read.has(id)?'2026-10-30T00:00:00Z':null}}
    else value={status:'not_checked'}
    await dev.call('Fetch.fulfillRequest',{requestId:p.requestId,responseCode:status,responseHeaders:headers,body:Buffer.from(status===503?'image temporarily unavailable':typeof value==='string'?value:JSON.stringify(value)).toString('base64')}).catch(e=>{if(!/Invalid InterceptionId|closed|not open|Invalid state/i.test(e.message))failures.push(e.message)})
  })
  await dev.call('Network.enable');await dev.call('Runtime.enable');await dev.call('Page.enable');await dev.call('Emulation.setDeviceMetricsOverride',{width:1440,height:900,deviceScaleFactor:1,mobile:false});await dev.call('Fetch.enable',{patterns:[{urlPattern:'*/api/*'},{urlPattern:'*/fixture/*'}]})
  const evaluate=async expression=>{const result=await dev.call('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||result.exceptionDetails.text);return result.result.value}
  await dev.call('Page.navigate',{url:base});await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===18"));await sleep(600)
  const initialImages=requests.length
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
  await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===18"))
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
  result.latestThirdPage=await roundTrip(48)
  result.latestPageSaved=await evaluate('history.state.eryouView.page')
  result.savedImageFilter=await evaluate('history.state.eryouView.withImages')
  result.savedRatings=await evaluate('history.state.eryouView.ratings')
  if(!result.savedImageFilter||JSON.stringify(result.savedRatings)!=='["UNKNOWN"]')throw Error('Image/rating filter lost')
  if(result.latestPageSaved!==2)throw Error('Third-page index not preserved')
  await clickText('订阅动态');await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length===18"))
  result.subscriptions=await roundTrip(10)
  result.subscriptionFeed=await evaluate('history.state.eryouView.feed')
  if(result.subscriptionFeed!=='subscriptions')throw Error('Subscription section lost')
  // Marked state already exists from mock auto-read; keep the read filter on return.
  await evaluate("Array.from(document.querySelector('[aria-label=\"已阅筛选\"]').querySelectorAll('button')).find(b=>b.textContent==='已阅').click()")
  await until(()=>evaluate("document.querySelectorAll('[data-mod-identity]').length>0&&document.querySelectorAll('[data-mod-identity]').length<18"))
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
  if(failures.length)throw Error('Browser exceptions: '+JSON.stringify(failures))
  fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(result,null,2));console.log(JSON.stringify({...result,report:path.join(out,'report.json')},null,2))
  await dev.call('Browser.close').catch(()=>{})
}finally{if(dev)dev.close();if(browser&&!browser.killed)browser.kill();if(vite&&!vite.killed)vite.kill()}})().catch(e=>{console.error(e);process.exitCode=1})

