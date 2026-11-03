import {useEffect,useState} from 'react'
import {Avatar,type Author} from './Authors'
export default function DetailAuthor({source,authorId,name,onOpen}:{source:string;authorId:number;name:string;onOpen:(a:Author)=>void}){
 const [author,setAuthor]=useState<Author>({source,author_id:authorId,name})
 useEffect(()=>{const c=new AbortController();fetch('/api/author?'+new URLSearchParams({source,author_id:String(authorId)}),{signal:c.signal}).then(async r=>{if(!r.ok)throw Error();return r.json()}).then(v=>{if(v.items[0])setAuthor(v.items[0])}).catch(()=>{});return()=>c.abort()},[source,authorId])
 return <button className="detail-author" onClick={()=>onOpen(author)}><Avatar author={author}/><span>{author.name||name}<small>查看本地收录作品 →</small></span></button>
}
