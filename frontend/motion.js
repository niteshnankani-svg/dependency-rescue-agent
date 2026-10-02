import {animate,stagger} from 'motion';
const preference=matchMedia('(prefers-reduced-motion: reduce)');
const button=document.getElementById('motion-toggle');
let enabled=!preference.matches, animations=[];
function update(){
  animations.forEach(a=>a.cancel()); animations=[];
  document.documentElement.dataset.motion=enabled?'on':'off';
  button.textContent=enabled?'◌ Motion on':'◌ Motion off';
  button.setAttribute('aria-pressed',String(enabled));
  if(!enabled || document.hidden) return;
  animations.push(animate('.signal',{strokeDashoffset:[60,0]},{duration:2.5,repeat:Infinity,ease:'linear'}));
  animations.push(animate('.core-halo',{opacity:[.25,.7,.25]},{duration:4,repeat:Infinity}));
}
button.addEventListener('click',()=>{enabled=!enabled;update();});
preference.addEventListener('change',()=>{enabled=!preference.matches;update();});
document.addEventListener('visibilitychange',update);
if(enabled) animate('.heading-row,.pipeline-card,.overview,.case-card',{opacity:[0,1],y:[12,0]},{duration:.6,delay:stagger(.08)});
update();
