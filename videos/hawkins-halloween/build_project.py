"""Build small scene hosts and a Huashu rendering/QA adapter from this project's artwork."""
from pathlib import Path
import json
import shutil

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
ENGINE_SOURCE = Path.home()/'.codex/skills/huashu-art-motion/scripts/engine'
ENGINE = REPO/'output/promo/hawkins-halloween-20261023/代码工程'
SHOTS = [('dice',3),('radio',3),('route',4),('street',4),('anomaly',4),('torch',4),('choice',4),('player',4),('input',4),('return',3),('enter',3)]
FONT = "@font-face{font-family:YaHei;src:local('Microsoft YaHei');font-weight:100 900}"

scenes = ROOT/'compositions'
scenes.mkdir(exist_ok=True)
start = 0
hosts = []
for name, duration in SHOTS:
    hosts.append(f'<div id="{name}" class="clip" data-composition-id="{name}" data-composition-src="compositions/{name}.html" data-start="{start}" data-duration="{duration}" data-track-index="1" data-track-kind="graphics" data-width="1080" data-height="1920"></div>')
    (scenes/f'{name}.html').write_text(f'''<template>
<style>#root{{position:absolute;inset:0}}canvas{{display:block;width:100%;height:100%}}</style>
<div id="root" data-composition-id="{name}" data-width="1080" data-height="1920"><canvas id="{name}-paint" width="1080" height="1920" aria-label="{name} scene"></canvas></div>
<script>
window.HawkinsPaint.ready.then(() => {{
 const canvas = document.getElementById('{name}-paint');
 const c = canvas.getContext('2d',{{willReadFrequently:true}});
 const clock = {{t:0}};
 const tl = gsap.timeline({{paused:true}});
 tl.fromTo(clock,{{t:0}},{{t:{duration},duration:{duration},ease:'none',onUpdate:()=>window.HawkinsPaint.draw(c,'{name}',clock.t)}},0);
 window.HawkinsPaint.draw(c,'{name}',0);
 window.__timelines['{name}'] = tl;
}});
</script>
</template>''',encoding='utf-8')
    start += duration

(ROOT/'index.html').write_text(f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=1080,height=1920">
<title>故事之间 · 万圣夜，别松手</title>
<script src="assets/gsap.min.js"></script>
<style>{FONT}*{{box-sizing:border-box;margin:0}}html,body{{width:1080px;height:1920px;overflow:hidden;background:#111311}}#root{{position:relative;width:100%;height:100%}}.clip{{position:absolute;inset:0}}</style>
<script src="assets/art.js"></script></head><body>
<div id="root" data-composition-id="main" data-start="0" data-duration="40" data-width="1080" data-height="1920">
{chr(10).join(hosts)}
<audio id="soundtrack" class="clip" src="assets/soundtrack.wav" data-start="0" data-duration="40" data-track-index="2" data-volume="1"></audio>
</div><script>
window.__timelines=window.__timelines||{{}};
window.HawkinsPaint.ready.then(()=>{{const clock={{t:0}};const tl=gsap.timeline({{paused:true}});tl.to(clock,{{t:40,duration:40,ease:'none'}});window.__timelines.main=tl;}});
</script></body></html>''',encoding='utf-8')

if not ENGINE.exists():
    shutil.copytree(ENGINE_SOURCE, ENGINE)
shutil.copytree(ROOT/'assets', ENGINE/'assets', dirs_exist_ok=True)
adapters = "window.FILM_SIZE=[1080,1920];window.FILM_DURATION=40;window.SCENE_LIBS=['assets/art.js'];\n"
adapters += 'window.ERAS='+json.dumps([{'id':name,'dur':d,'counter':{'draw':None}} for name,d in SHOTS])+';\n'
# Override only the decorative counter and adapt the same scene functions for QA.
adapters += "for(const e of ERAS){e.counter={draw:()=>{}};e.draw=(c,lt)=>HawkinsPaint.draw(c,e.id,lt);}\n"
(ENGINE/'eras.js').write_text(adapters,encoding='utf-8')
html = (ENGINE_SOURCE/'index.html').read_text(encoding='utf-8')
html = html.replace('<style>', '<style>'+FONT,1)
html = html.replace('<script src="engine.js"></script>', '<script>HawkinsPaint.ready.then(()=>{const s=document.createElement("script");s.src="engine.js";document.body.appendChild(s);});</script>')
(ENGINE/'index.html').write_text(html,encoding='utf-8')
engine_js = (ENGINE_SOURCE/'engine.js').read_text(encoding='utf-8')
(ENGINE/'engine.js').write_text(engine_js.replace("getContext('2d')", "getContext('2d', {willReadFrequently:true})"),encoding='utf-8')
print(f'{len(SHOTS)} shots / {start}s; Huashu adapter: {ENGINE}')
