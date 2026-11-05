(()=>{
  const root=document.documentElement;
  const mq=matchMedia('(prefers-color-scheme: light)');
  let saved=null;try{saved=localStorage.getItem('navichno-theme')}catch(e){}
  if(saved)root.dataset.theme=saved;
  document.querySelector('[data-theme-toggle]').addEventListener('click',()=>{
    const cur=root.dataset.theme||(mq.matches?'light':'dark');
    const next=cur==='light'?'dark':'light';
    root.dataset.theme=next;try{localStorage.setItem('navichno-theme',next)}catch(e){}
  });
  const mnav=document.querySelector('[data-mnav]'),burger=document.querySelector('[data-burger]');
  const setNav=(o,focusBack=true)=>{mnav.classList.toggle('open',o);mnav.setAttribute('aria-hidden',String(!o));burger.setAttribute('aria-expanded',String(o));document.body.classList.toggle('lock',o);if(o)setTimeout(()=>mnav.querySelector('.mnav__close').focus(),250);else if(focusBack)burger.focus()};
  burger.addEventListener('click',()=>setNav(true));
  mnav.querySelectorAll('[data-mnav-close]').forEach(b=>b.addEventListener('click',()=>setNav(false)));
  mnav.querySelectorAll('.mnav__links a,[data-mnav-link]').forEach(a=>a.addEventListener('click',()=>setNav(false,false)));
  addEventListener('keydown',e=>{if(e.key==='Escape'&&mnav.classList.contains('open'))setNav(false)});
  matchMedia('(min-width:901px)').addEventListener('change',e=>{if(e.matches)setNav(false,false)});
  const pl=document.querySelector('.plans'),pd=document.querySelector('[data-plans-dots]');
  if(pl&&pd){const cards=[...pl.children];cards.forEach((c,i)=>{const b=document.createElement('button');b.type='button';b.setAttribute('aria-label','Формат '+(i+1));b.onclick=()=>c.scrollIntoView({behavior:'smooth',inline:'center',block:'nearest'});pd.appendChild(b)});
    const upd=()=>{const mid=pl.scrollLeft+pl.clientWidth/2;let best=0,d=1e9;cards.forEach((c,i)=>{const cm=c.offsetLeft+c.offsetWidth/2;const dd=Math.abs(cm-mid);if(dd<d){d=dd;best=i}});[...pd.children].forEach((b,i)=>b.setAttribute('aria-current',i===best))};
    pl.addEventListener('scroll',()=>requestAnimationFrame(upd),{passive:true});upd();}
  const mb=document.querySelector('[data-more]'),ft=document.querySelector('#inside .features');
  if(mb&&ft)mb.addEventListener('click',()=>{const o=!ft.classList.contains('open');ft.classList.toggle('open',o);mb.setAttribute('aria-expanded',o);mb.querySelector('[data-more-label]').textContent=o?'Згорнути':'Гортайте далі';if(!o)ft.scrollIntoView({behavior:'smooth',block:'start'})});
  const top=document.getElementById('top');
  const onScroll=()=>top.classList.toggle('scrolled',scrollY>8);
  addEventListener('scroll',onScroll,{passive:true});onScroll();

  const tones={
    olive:{name:'Олива · стримано й гідно',dark:['#171b16','#efe9d8','#a7a493','#d7b46a'],light:['#f1ede0','#20251e','#64685a','#7a6122']},
    graphite:{name:'Графіт · строго й спокійно',dark:['#17181b','#ebebe8','#a1a2a6','#c9c3b4'],light:['#f1f1ef','#1e2024','#626469','#4a4d55']},
    sky:{name:'Небо · світло й тихо',dark:['#121a24','#e8edf2','#9aa8b8','#e0c06a'],light:['#eef2f6','#18263a','#5b6b7e','#2f5b8a']},
    sand:{name:'Пісок · тепло й по-домашньому',dark:['#1f1a14','#f1e7d6','#b3a68f','#d9a95e'],light:['#f6efe2','#2c2318','#76694f','#9a6b2a']},
    wine:{name:'Калина · глибоко й по-родинному',dark:['#1d1314','#f2e6e3','#b59c99','#d8a35c'],light:['#f6eeec','#2b1618','#7a5d5b','#8c2f35']}
  };
  let mode='dark',tone='olive';
  const pv=document.querySelector('[data-preview]'),nm=document.querySelector('[data-tone-name]');
  const paint=()=>{const c=tones[tone][mode];pv.style.setProperty('--p-bg',c[0]);pv.style.setProperty('--p-text',c[1]);pv.style.setProperty('--p-muted',c[2]);pv.style.setProperty('--p-acc',c[3]);nm.textContent=tones[tone].name+(mode==='light'?', світла тема':', темна тема')};
  document.querySelectorAll('[data-mode]').forEach(b=>b.addEventListener('click',()=>{mode=b.dataset.mode;document.querySelectorAll('[data-mode]').forEach(x=>x.setAttribute('aria-pressed',x===b));paint()}));
  document.querySelectorAll('[data-tone]').forEach(b=>b.addEventListener('click',()=>{tone=b.dataset.tone;document.querySelectorAll('[data-tone]').forEach(x=>x.setAttribute('aria-pressed',x===b));paint()}));
  paint();
})();