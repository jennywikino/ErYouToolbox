import { test } from 'node:test'
import assert from 'node:assert/strict'
import {listingPreferences,resizedPage,cardPreviewUrl,sourceUpdateDate,dateLabel} from './policy.ts'
import {createStartupRequest} from './autoStartup.ts'
import {globalSearchContext} from './policy.ts'
import {gameBananaModId} from './policy.ts'
import {syncFailureCount} from './policy.ts'

test('sync failures include author pending items and legacy failed reports',()=>{
 assert.equal(syncFailureCount({status:'success',failures:[]}),0)
 assert.equal(syncFailureCount({status:'partial',failures:[],authors:{status:'partial',pending_count:2}}),2)
 assert.equal(syncFailureCount({status:'failed',failures:[],error:'backup failed'}),1)
 assert.equal(syncFailureCount({status:'partial',failure_count:3,failures:[{}]}),3)
})

test('manual import accepts official MOD links or IDs and rejects unsafe addresses',()=>{
 for(const text of ['541855',' https://gamebanana.com/mods/541855 ','https://www.gamebanana.com/mods/541855/?x=1#comments'])assert.equal(gameBananaModId(text),541855)
 for(const text of ['0','-1','1.2','9007199254740993','javascript:alert(1)','https://gamebanana.com.evil.test/mods/1','https://user@gamebanana.com/mods/1','https://gamebanana.com/members/1','https://gamebanana.com:444/mods/1'])assert.equal(gameBananaModId(text),null)
})

test('unconfigured startup delegates one-shot import to the server once',async()=>{
 let posts=0
 const request=(async (_url:RequestInfo|URL,init?:RequestInit)=>{if(init)posts++;return new Response(JSON.stringify(init?{status:'requested'}:{configured:false,settings:{mode:'off'}}))}) as typeof fetch
 const start=createStartupRequest(request)
 await Promise.all([start(),start()]);assert.equal(posts,1)
 await start();assert.equal(posts,1)
})

test('global search clears stale Jane Doe context and retains game and personal preferences',()=>{
 const result=globalSearchContext({game:'8552',draft:' 胡桃 ',category:'Skins',subcategory:'Jane Doe',author:{author_id:1},page:4,readFilter:'unread',pageSize:25,viewMode:'compact'})
 assert.equal(result.search,'胡桃');assert.equal(result.category,'');assert.equal(result.subcategory,'');assert.equal(result.author,null);assert.equal(result.page,0)
 assert.equal(result.game,'8552');assert.equal(result.readFilter,'unread');assert.equal(result.pageSize,25);assert.equal(result.viewMode,'compact')
})

test('navigation and repeated startup calls never schedule another document scan',async()=>{
 let count=0
 const request=(async (_url:RequestInfo|URL,init?:RequestInit)=>{if(init)count++;return new Response(JSON.stringify(init?{status:'requested'}:{settings:{mode:'off'}}))}) as typeof fetch
 const start=createStartupRequest(request)
 for(const game of ['8552','18366','19567','20357','21842','23012']){void game;await start()}
 await Promise.all([start(),start()]);assert.equal(count,1)
})
import { canShowImages, imageIndex, safeUrl, discoveryTime, syncTimeLabel, syncStatusLabel, subscriptionActivity, restoreScrollTop, restorePopularView, validBrowseSnapshot } from './policy.ts'

test('startup is once per document, legacy modes do not suppress the one-shot import', async () => {
  for(const mode of ['off','check','apply']){
    const calls: {url:string;init?:RequestInit}[]=[]
    const start=createStartupRequest((async (url:RequestInfo|URL,init?:RequestInit)=>{
      calls.push({url:String(url),init})
      return new Response(JSON.stringify(init?{status:'requested'}:{settings:{mode}}),{status:200})
    }) as typeof fetch)
    const first=start();assert.equal(first,start());await Promise.all([first,start()])
    assert.equal(calls.length,2)
    {
      assert.equal(calls[1].url,'/api/auto-sync/startup')
      assert.equal(calls[1].init?.body,'{}') // Never forces or changes saved mode.
    }
  }
})

test('startup errors remain visible without automatic retry loops', async () => {
  let requests=0
  const start=createStartupRequest((async()=>{requests++;throw Error('offline')}) as typeof fetch)
  await assert.rejects(start(),/offline/);await assert.rejects(start(),/offline/)
  assert.equal(requests,1)
})

test('retired content policies and legacy hidden preferences no longer hide images',()=>{
 for(const rating of ['UNKNOWN','ADULT','NSFW','SAFE'])for(const code of ['UNKNOWN','-','pn','nu','sc','rp'])
  assert.equal(canShowImages(rating,false,[code],false,false),true)
})
test('legacy explicit image preferences remain harmless compatibility arguments',()=>{
 assert.equal(canShowImages('ADULT',true,['pn'],true,true),true)
 assert.equal(safeUrl('javascript:alert(1)'),null)
})

test('gallery index respects first, last, and empty image boundaries', () => {
  assert.equal(imageIndex(-1, 6), 0)
  assert.equal(imageIndex(6, 6), 5)
  assert.equal(imageIndex(2, 6), 2)
  assert.equal(imageIndex(1, 0), 0)
})
test('external links reject executable and credential-bearing URLs', () => {
  assert.equal(safeUrl('javascript:alert(1)'), null)
  assert.equal(safeUrl('https://user:pass@example.com'), null)
  assert.equal(safeUrl('https://gamebanana.com/mods/732438'), 'https://gamebanana.com/mods/732438')
})

test('source release, source update and local discovery use separate timestamps', () => {
  const mod = {created_at: '2020-01-01', updated_at: '2026-10-28', first_seen_at: '2026-10-29'}
  assert.deepEqual(discoveryTime(mod, 'created'), {label: '来源发布', value: '2020-01-01'})
  assert.deepEqual(discoveryTime(mod, 'updated'), {label: '来源更新', value: '2026-10-28'})
  assert.deepEqual(discoveryTime(mod, 'first_seen'), {label: '本地发现', value: '2026-10-29'})
  assert.equal(discoveryTime({created_at: '2026-10-29'}, 'updated').value, '2026-10-29')
  assert.deepEqual(sourceUpdateDate({created_at:'2026-10-29',updated_at:'invalid'}),{value:'2026-10-29',hasIndependentUpdate:false})
  assert.deepEqual(sourceUpdateDate({}),{value:null,hasIndependentUpdate:false})
  assert.equal(dateLabel(null),'暂无来源数据')
})

test('sync time and status never turn failure or missing data into success', () => {
  assert.equal(syncTimeLabel(null), '暂无时间')
  assert.equal(syncTimeLabel('invalid'), '暂无时间')
  assert.match(syncTimeLabel('2026-10-29T00:00:00Z'), /UTC$/)
  assert.equal(syncStatusLabel('failed'), '失败')
  assert.equal(syncStatusLabel('partial'), '部分成功')
  assert.equal(syncStatusLabel('unexpected'), '未知状态')
})

test('subscription history and new events stay distinct', () => {
  const base = {subscription_followed_at:'2026-10-29', created_at:'2020-01-01',local_first_seen_event_at:'2026-10-30'}
  assert.equal(subscriptionActivity(base),'已收录历史作品')
  assert.equal(subscriptionActivity({...base,created_at:'2026-10-30'}),'关注后新发布')
  assert.equal(subscriptionActivity({...base,source_update_detected_at:'2026-10-30'}),'关注后确认来源更新')
  assert.equal(subscriptionActivity({...base,source_update_detected_at:'2020-01-01'}),'已收录历史作品')
})

test('anchor restoration uses saved viewport offset, pixels are fallback',()=>{
  assert.equal(restoreScrollTop(500,1000,200,99),1300)
  assert.equal(restoreScrollTop(null,1000,200,99),99)
  assert.equal(restoreScrollTop(0,0,200,99),0)
  assert.equal(restoreScrollTop(null,0,0,NaN),0)
})
test('popular query and per-game pages survive history serialization',()=>{
  const value={sort:'views',scope:'recent',days:90,maxPages:3,groups:{8552:{loaded:true,page:3},18366:{loaded:false,page:1}}}
  assert.deepEqual(restorePopularView(JSON.parse(JSON.stringify(value))),value)
  assert.deepEqual(restorePopularView(undefined),{sort:'likes',scope:'recent',days:30,maxPages:2,groups:{}})
  assert.equal(restorePopularView({groups:{8552:{page:-1,loaded:true}},days:8}).days,30)
})
test('missing or malformed history is ignored rather than crashing a refreshed detail',()=>{
  const snapshot={feed:'latest',game:'8552',draft:'test',search:'test',sort:'created',readFilter:'all',anchor:'gamebanana:Mod:1',page:2,scrollY:800,anchorTop:200,withImages:false,allowUnknown:true,ratings:null}
  assert.equal(validBrowseSnapshot(snapshot),true)
  assert.equal(validBrowseSnapshot({...snapshot,author:{source:'gamebanana',author_id:7}}),true)
  assert.equal(validBrowseSnapshot({...snapshot,author:{source:'gamebanana',author_id:0}}),false)
  assert.equal(validBrowseSnapshot({...snapshot,author:{source:'gamebanana',author_id:'7'}}),false)
  assert.equal(validBrowseSnapshot({...snapshot,pageSize:50,viewMode:'compact'}),true)
  assert.equal(validBrowseSnapshot({...snapshot,pageSize:51}),false)
  assert.equal(validBrowseSnapshot({...snapshot,pageSize:'25'}),false)
  assert.equal(validBrowseSnapshot({...snapshot,category:'Skins',subcategory:'Baizhi'}),true)
  assert.equal(validBrowseSnapshot({...snapshot,category:{name:'invalid'}}),false)
  assert.equal(validBrowseSnapshot({...snapshot,viewMode:'unknown'}),false)
  for(const value of [undefined,{}, {...snapshot,ratings:{}},{...snapshot,page:-1},{...snapshot,scrollY:Infinity}])assert.equal(validBrowseSnapshot(value),false)
})

test('listing defaults and persisted preferences accept only supported densities and sizes',()=>{
  assert.deepEqual(listingPreferences(null),{viewMode:'compact',pageSize:25})
  for(const pageSize of [15,25,50])for(const viewMode of ['compact','standard']){
    const value={viewMode,pageSize}
    assert.deepEqual(listingPreferences(JSON.parse(JSON.stringify(value))),value)
  }
  assert.deepEqual(listingPreferences({viewMode:'unsafe',pageSize:1000}),{viewMode:'compact',pageSize:25})
})

test('changing page size keeps the former first item on the new page and clamps bounds',()=>{
  for(const oldSize of [15,25,50])for(const newSize of [15,25,50])for(let page=0;page<4;page++){
    const next=resizedPage(page,oldSize,newSize,797)
    assert.ok(next*newSize<=page*oldSize)
    assert.ok((next+1)*newSize>page*oldSize)
  }
  assert.equal(resizedPage(3,25,50,0),0)
  assert.equal(resizedPage(30,25,50,60),1)
})

test('compact covers prefer saved thumbnails and never choose a gallery original over them',()=>{
  const mod={preview_urls:['https://images.gamebanana.com/img/ss/mods/card.jpg'],preview_images:[{image_url:'https://images.gamebanana.com/img/ss/mods/original.jpg',thumbnail_url:'https://images.gamebanana.com/img/ss/mods/530-small.jpg',switch_url:'https://images.gamebanana.com/img/ss/mods/100-small.jpg'}]}
  assert.equal(cardPreviewUrl(mod,true),mod.preview_images[0].thumbnail_url)
  assert.equal(cardPreviewUrl(mod,false),mod.preview_urls[0])
  assert.equal(cardPreviewUrl({preview_urls:[],preview_images:[{thumbnail_url:'javascript:bad',switch_url:mod.preview_images[0].switch_url}]},true),mod.preview_images[0].switch_url)
  assert.equal(cardPreviewUrl({preview_urls:mod.preview_urls},true),mod.preview_urls[0])
  assert.equal(cardPreviewUrl({preview_urls:[]},true),null)
})
