export const canonical = s => s.normalize('NFKC').toLocaleLowerCase('ru').replace(/\p{M}/gu,'').replace(/\s+/g,' ').trim();
export const selectedEvents = (d,f={}) => d.events.filter(e=>(!f.from||e.date>=f.from)&&(!f.to||e.date<=f.to)&&(!f.format||e.format===f.format)&&(!f.query||canonical(e.title+' '+e.teams.map(t=>t.name).join(' ')).includes(canonical(f.query))));
export function summary(events){
 const teams=new Map();let visits=0,entries=0,known=0,registrations=0;
 for(const e of events){if(e.attended===true){known++;visits+=e.teams.reduce((a,t)=>a+t.size,0);for(const t of e.teams.filter(t=>t.kind==='team')){entries++;const k=canonical(t.name);const v=teams.get(k)||{name:t.name,games:0,players:0,history:[]};v.games++;v.players+=t.size;v.history.push({date:e.date,title:e.title,size:t.size});teams.set(k,v);}}registrations+=e.teams.length;}
 const rows=[...teams.values()].sort((a,b)=>b.games-a.games||a.name.localeCompare(b.name,'ru'));
 return {games:events.length,known,visits,entries,average:known?entries/known:null,teams:rows,uniqueTeams:rows.length,returning:rows.filter(t=>t.games>1).length,registrations};
}
const dateOK=s=>typeof s==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(s)&&!isNaN(Date.parse(s+'T00:00:00Z'))&&new Date(s+'T00:00:00Z').toISOString().slice(0,10)===s;
const str=(s,max=180)=>{if(typeof s!=='string'||!s.trim()||s.length>max)throw Error('Некорректное текстовое поле');return s.trim();};
const count=n=>{if(!Number.isSafeInteger(n)||n<0||n>10000000)throw Error('Некорректное число');return n;};
export function validate(raw){
 if(raw?.schema_version!==1||!Array.isArray(raw.events)||raw.events.length>5000)throw Error('Нужен JSON RAZUMBOY schema_version: 1');
 const ids=new Set();const events=raw.events.map(e=>{const id=str(String(e.id),80);if(ids.has(id))throw Error('Повторяющийся ID игры');ids.add(id);if(!dateOK(e.date))throw Error('Дата игры должна иметь формат YYYY-MM-DD');if(![true,false,null].includes(e.attended))throw Error('Неизвестный статус явки');if(!Array.isArray(e.teams)||e.teams.length>1000)throw Error('Некорректный список команд');
 const names=new Set();return {id,date:e.date,title:str(e.title),format:str(e.format,40),attended:e.attended,source:str(e.source||'Импорт',250),teams:e.teams.map(t=>{if(!['team','guest'].includes(t.kind))throw Error('Тип записи: team или guest');const name=str(t.name,120);const k=canonical(name);if(t.kind==='team'&&names.has(k))throw Error('Повтор команды в одной игре');names.add(k);const size=count(t.size);if(size<1||size>1000)throw Error('Размер группы: 1–1000');return {name,size,kind:t.kind};}),cancelled:count(e.cancelled||0),funnel:cleanFunnel(e.funnel)};});
 const competitors=Array.isArray(raw.competitors)?raw.competitors.slice(0,100).map(c=>({name:str(c.name,80),games:count(c.games),entries:count(c.entries),language:str(c.language,20),source:str(c.source,250)})):[];
 return {schema_version:1,as_of:str(raw.as_of||'Не указан',80),source_label:str(raw.source_label||'Загруженный снимок',200),events,competitors};
}
function cleanFunnel(f){if(f==null)return null;const keys=['bot_starts','registrations_started','registrations_completed'];const out={};for(const k of keys)out[k]=count(f[k]);return out;}
export const csvCell=x=>'"'+String(x??'').replace(/^[=+@\-\t\r]/,'\'$&').replaceAll('"','""')+'"';
export const csv=events=>'\ufeff'+[['Дата','Игра','Команд','Игроков','Явка'],...events.map(e=>[e.date,e.title,e.teams.filter(t=>t.kind==='team').length,e.teams.reduce((a,t)=>a+t.size,0),e.attended===true?'Подтверждена':e.attended===false?'Не было':'Неизвестна'])].map(r=>r.map(csvCell).join(';')).join('\r\n');
