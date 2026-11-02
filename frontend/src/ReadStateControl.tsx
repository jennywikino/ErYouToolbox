import {useEffect,useRef,useState} from 'react'
import {syncTimeLabel} from './policy'
export default function ReadStateControl({source,itemId,initial,auto=false,onChange,compact=false}:{source:string;itemId:number;initial?:boolean|number;auto?:boolean;onChange:()=>void;compact?:boolean}){
  const [read,setRead]=useState(!!initial),[first,setFirst]=useState<string|null>(null),[error,setError]=useState(''),[busy,setBusy]=useState(false),[ready,setReady]=useState(true)
  const callback=useRef(onChange);callback.current=onChange
  useEffect(()=>{if(!auto)setRead(!!initial)},[initial,auto])
  async function write(value:boolean){
    const response=await fetch('/api/read-state',{method:'POST',headers:{'Content-Type':'application/json','X-ErYouToolbox':'1'},body:JSON.stringify({source,item_id:itemId,is_read:value})})
    const data=await response.json();if(!response.ok)throw Error(data.error)
    return data as {is_read:boolean;first_viewed_at:string|null}
  }
  useEffect(()=>{if(!auto)return;let alive=true;setBusy(true)
    fetch('/api/read-state?'+new URLSearchParams({source,item_id:String(itemId)})).then(async r=>{const value=await r.json();if(!r.ok)throw Error(value.error);return value})
      .then(async value=>{if(!alive)return;if(!value.available){setReady(false);setRead(value.is_read);setError('需先手动迁移已阅时间字段');return}
        const saved=await write(true);if(alive){setRead(saved.is_read);setFirst(saved.first_viewed_at)}callback.current()})
      .catch(e=>{if(alive)setError(e.message)}).finally(()=>{if(alive)setBusy(false)})
    return()=>{alive=false}
  },[source,itemId,auto])
  async function toggle(){setBusy(true);setError('');try{const value=await write(!read);setRead(value.is_read);setFirst(value.first_viewed_at);callback.current()}catch(e){setError(e instanceof Error?e.message:'状态保存失败')}finally{setBusy(false)}}
  return <div className={`read-state-control mx-4 my-3 text-xs text-slate-500${compact?' compact-read':''}`}>
    {read&&<span className="mr-3">已阅</span>}<button className="small-button" disabled={busy||!ready} onClick={toggle}>{busy?'保存中…':read?'恢复未阅':'标记已阅'}</button>
    {auto&&first&&<p className="mt-2">首次记录浏览：{syncTimeLabel(first)}</p>}
    {error&&<p className="mt-2 text-red-600" role="alert">{error}</p>}
  </div>
}
