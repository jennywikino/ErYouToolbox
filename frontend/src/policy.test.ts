import { test } from 'node:test'
import assert from 'node:assert/strict'
import { canShowImages, imageIndex, safeUrl, discoveryTime, syncTimeLabel, syncStatusLabel, subscriptionActivity, restoreScrollTop, restorePopularView, validBrowseSnapshot } from './policy.ts'

test('image display preference is independent of source classification', () => {
  assert.equal(canShowImages('UNKNOWN', false), false)
  assert.equal(canShowImages('UNKNOWN', true), true)
  assert.equal(canShowImages('SAFE', false), false)
})
test('image preference also allows adult and unverified ratings', () => {
  for (const value of ['ADULT', 'NSFW', 'OTHER', '']) assert.equal(canShowImages(value, true), true)
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
  assert.equal(discoveryTime({created_at: '2026-10-29'}, 'updated').value, undefined)
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
  for(const value of [undefined,{}, {...snapshot,ratings:{}},{...snapshot,page:-1},{...snapshot,scrollY:Infinity}])assert.equal(validBrowseSnapshot(value),false)
})
