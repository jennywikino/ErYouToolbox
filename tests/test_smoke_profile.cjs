const {test}=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os')
const {cleanup}=require('./smoke_profile.cjs')
for(const scenario of ['success','failure','abnormal','active','locked','wrong-path'])test(scenario,async()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'smoke-life-')),out=path.join(root,'logs/ui_smoke/run'),profile=path.join(out,'profile')
 fs.mkdirSync(profile,{recursive:true});fs.writeFileSync(path.join(profile,'cache'),'test');fs.writeFileSync(path.join(out,'report.json'),'{}');fs.writeFileSync(path.join(out,'error.log'),scenario)
 const browser={pid:123,exitCode:0,signalCode:null}
 const result=await cleanup({root,out,profile:scenario==='wrong-path'?root:profile,browser,close:async()=>{if(scenario==='active')throw Error('Browser still active');if(scenario==='abnormal')browser.exitCode=1},inspect:async()=>{if(scenario==='locked')throw Error('File in use')}})
 assert.equal(result.status,['active','locked','wrong-path'].includes(scenario)?'retained':'removed')
 assert.ok(fs.existsSync(path.join(out,'report.json')));assert.equal(fs.readFileSync(path.join(out,'error.log'),'utf8'),scenario)
 if(result.status==='retained')assert.ok(fs.existsSync(profile))
 // Test-owned temporary tree only; never a project profile.
 fs.rmSync(root,{recursive:true})
})
