/* Original tabletop artwork. Shared by the HyperFrames scenes and the Huashu QA adapter. */
(() => {
  const W = 1080, H = 1920;
  const C = { dark: '#111311', wood: '#262b25', paper: '#b1a17b', ink: '#363d30', light: '#e9d9bb', orange: '#c37732', red: '#80282a' };
  const clamp = v => Math.max(0, Math.min(1, v));
  const ease = v => { v = clamp(v); return 1 - Math.pow(1 - v, 4); };
  const smooth = v => { v = clamp(v); return v * v * (3 - 2 * v); };
  const lerp = (a, b, p) => a + (b - a) * p;
  function random(seed) { return () => { seed |= 0; seed = seed + 0x6d2b79f5 | 0; let a = Math.imul(seed ^ seed >>> 15, 1 | seed); a ^= a + Math.imul(a ^ a >>> 7, 61 | a); return ((a ^ a >>> 14) >>> 0) / 4294967296; }; }
  function buffer(w, h) { const cv = document.createElement('canvas'); cv.width = w; cv.height = h; return cv; }
  function path(c, points, close = false) { c.beginPath(); points.forEach((p, i) => i ? c.lineTo(...p) : c.moveTo(...p)); if (close) c.closePath(); }
  function rounded(c, x, y, w, h, r, fill, stroke) { c.beginPath(); c.roundRect(x, y, w, h, r); if (fill) { c.fillStyle = fill; c.fill(); } if (stroke) { c.strokeStyle = stroke; c.stroke(); } }
  function line(c, pts, color, width = 2) { path(c, pts); c.strokeStyle = color; c.lineWidth = width; c.lineCap = 'round'; c.lineJoin = 'round'; c.stroke(); }
  function text(c, s, x, y, size, color = C.light, align = 'left', face = 'YaHei') { c.fillStyle = color; c.font = `${size >= 60 ? 600 : 400} ${size}px ${face}`; c.textAlign = align; c.textBaseline = 'alphabetic'; c.fillText(s, x, y); }
  function shadow(c, blur = 24, y = 12) { c.shadowColor = '#050805b0'; c.shadowBlur = blur; c.shadowOffsetX = 5; c.shadowOffsetY = y; }
  function unshadow(c) { c.shadowColor = 'transparent'; c.shadowBlur = 0; c.shadowOffsetX = c.shadowOffsetY = 0; }

  const grain = random(19841031);
  const wood = buffer(W, H), wc = wood.getContext('2d', {willReadFrequently:true});
  wc.fillStyle = C.wood; wc.fillRect(0, 0, W, H);
  for (let y = -H; y < H * 2; y += 7) {
    wc.beginPath(); wc.moveTo(0, y); wc.bezierCurveTo(300, y + 20, 800, y - 25, W, y + 34);
    wc.strokeStyle = grain() > .5 ? '#53513a28' : '#080f0b38'; wc.lineWidth = 1 + grain() * 3; wc.stroke();
  }
  [345, 728].forEach(x => { wc.fillStyle = '#070c0999'; wc.fillRect(x, 0, 3, H); wc.fillStyle = '#81826819'; wc.fillRect(x + 4, 0, 2, H); });
  for (let i = 0; i < 14500; i++) { wc.fillStyle = i % 2 ? '#d8be7c0a' : '#00000013'; wc.fillRect(grain() * W, grain() * H, 1 + grain() * 14, .5 + grain()); }
  const pool = wc.createRadialGradient(190, 180, 100, 530, 780, 1700); pool.addColorStop(0, '#b1854933'); pool.addColorStop(.6, '#544d2b08'); pool.addColorStop(1, '#030805c0'); wc.fillStyle = pool; wc.fillRect(0, 0, W, H);

  const paper = buffer(850, 1220), pc = paper.getContext('2d', {willReadFrequently:true});
  pc.fillStyle = C.paper; pc.fillRect(0, 0, 850, 1220);
  for (let i = 0; i < 22000; i++) { pc.fillStyle = i % 3 ? '#fff4c10a' : '#59472612'; pc.fillRect(grain() * 850, grain() * 1220, grain() * 8 + .6, .7); }
  pc.strokeStyle = '#72634777'; pc.lineWidth = 2; pc.strokeRect(25, 25, 800, 1170);
  pc.strokeStyle = '#e2d0a73b'; pc.beginPath(); pc.moveTo(424, 10); pc.lineTo(424, 1210); pc.moveTo(10, 605); pc.lineTo(840, 605); pc.stroke();
  pc.strokeStyle = '#5d533535'; pc.beginPath(); pc.moveTo(428, 10); pc.lineTo(428, 1210); pc.moveTo(10, 609); pc.lineTo(840, 609); pc.stroke();
  text(pc, 'HAWKINS', 68, 116, 66, '#3c4434', 'left', 'Georgia');
  text(pc, 'OCTOBER 31 / 1984', 71, 155, 24, '#665d40', 'left', 'Georgia');
  line(pc, [[70, 180], [780, 180]], '#60593d', 2);
  for (let x = 80; x < 820; x += 70) line(pc, [[x, 210], [x, 1100]], '#655f3d20');
  for (let y = 220; y < 1140; y += 70) line(pc, [[60, y], [790, y]], '#655f3d20');
  const roads = [ [[120, 1000], [120, 810], [265, 810], [265, 620], [450, 620], [450, 385], [690, 385], [690, 260]], [[450, 620], [700, 620], [700, 900], [780, 900]], [[265, 810], [550, 810], [550, 1080]], [[120, 810], [70, 810]], [[450, 385], [230, 385], [230, 260]] ];
  roads.forEach(p => { line(pc, p, '#57543d', 19); line(pc, p, '#bfb18b', 12); });
  function house(c, x, y, s = 1) { c.save(); c.translate(x, y); c.scale(s, s); c.strokeStyle = '#5c5c41'; c.lineWidth = 2; path(c, [[-16, 0], [-16, -25], [0, -40], [16, -25], [16, 0]], true); c.stroke(); c.strokeRect(-4, -17, 9, 17); c.restore(); }
  [[82, 944], [83, 881], [167, 862], [215, 772], [300, 733], [300, 668], [403, 575], [497, 523], [495, 453], [620, 340], [737, 330], [655, 742], [746, 810], [600, 940]].forEach(([x, y], i) => house(pc, x, y, .8 + (i % 3) * .12));
  text(pc, 'WHEELER', 150, 1033, 27, '#54543b', 'left', 'Georgia');
  text(pc, 'MAPLE ST.', 300, 864, 27, '#54543b', 'left', 'Georgia');
  text(pc, 'HOME BEFORE NINE', 64, 1165, 25, '#685d3f', 'left', 'Georgia');
  pc.save(); pc.translate(755, 1050); line(pc, [[0, -55], [0, 55]], '#56583e', 2); line(pc, [[-35, 0], [35, 0]], '#56583e', 2); path(pc, [[0, -43], [12, 0], [0, -10], [-12, 0]], true); pc.fillStyle = '#575a3c'; pc.fill(); text(pc, 'N', 0, -70, 22, '#55563b', 'center', 'Georgia'); pc.restore();
  const route = [[120, 1000], [120, 810], [265, 810], [265, 620], [450, 620], [450, 385], [690, 385]];
  const distances = route.slice(1).map((p, i) => Math.hypot(p[0] - route[i][0], p[1] - route[i][1]));
  const totalDistance = distances.reduce((a, b) => a + b, 0);
  function routePoint(p) { let d = clamp(p) * totalDistance; for (let i = 0; i < distances.length; i++) { if (d <= distances[i]) { const k = d / distances[i]; return [lerp(route[i][0], route[i + 1][0], k), lerp(route[i][1], route[i + 1][1], k)]; } d -= distances[i]; } return route.at(-1); }
  function drawnRoute(c, p) { const end = routePoint(p); let remain = clamp(p) * totalDistance; const points = [route[0]]; for (let i = 0; i < distances.length; i++) { if (remain < distances[i]) break; points.push(route[i + 1]); remain -= distances[i]; } points.push(end); c.setLineDash([8, 7]); line(c, points, '#7d3029', 5); c.setLineDash([]); c.strokeStyle = '#7d3029'; c.lineWidth = 4; c.beginPath(); c.arc(120, 1000, 17, 0, Math.PI * 2); c.stroke(); return end; }

  function pencil(c, x, y, angle = -.6) { c.save(); c.translate(x, y); c.rotate(angle); shadow(c, 12, 8); path(c, [[0, 0], [-13, 48], [-13, 375], [13, 375], [13, 48]], true); c.fillStyle = '#a3833f'; c.fill(); unshadow(c); c.fillStyle = '#e1c17d'; c.fillRect(-11, 47, 7, 323); c.fillStyle = '#555d3a'; c.fillRect(4, 47, 8, 323); path(c, [[0, 0], [-13, 48], [13, 48]], true); c.fillStyle = '#d1b68b'; c.fill(); path(c, [[0, 0], [-4, 15], [4, 15]], true); c.fillStyle = '#252c22'; c.fill(); c.fillStyle = '#6c7563'; c.fillRect(-13, 370, 26, 24); c.fillStyle = '#98624e'; c.fillRect(-13, 394, 26, 25); c.restore(); }
  function map(c, p = .82, pen = false, dx = 0, dy = 0, angle = -.09) { c.save(); c.translate(105 + dx, 325 + dy); c.rotate(angle); shadow(c, 32, 20); c.drawImage(paper, 0, 0); unshadow(c); const end = drawnRoute(c, p); if (pen) pencil(c, ...end, -.85); c.restore(); }
  function screw(c, x, y) { c.fillStyle = '#6c755d'; c.beginPath(); c.arc(x, y, 5, 0, 7); c.fill(); line(c, [[x - 3, y - 2], [x + 3, y + 2]], '#151c14'); }
  function radio(c, x = 770, y = 1200, scale = 1, turn = 0) {
    c.save(); c.translate(x, y); c.rotate(.15); c.scale(scale, scale); shadow(c, 30, 22);
    rounded(c, -158, -285, 316, 580, 28, '#101812', '#606b50'); unshadow(c);
    const shell = c.createLinearGradient(-158, 0, 158, 0); shell.addColorStop(0, '#3d4935'); shell.addColorStop(.15, '#273322'); shell.addColorStop(.8, '#1a251c'); shell.addColorStop(1, '#46533c'); rounded(c, -149, -278, 298, 565, 23, shell, '#111b14');
    c.fillStyle = '#1c2619'; c.fillRect(-111, -674, 15, 396); c.fillStyle = '#778365'; c.fillRect(-106, -662, 4, 380); rounded(c, -117, -301, 29, 41, 5, '#0e170e');
    c.fillStyle = '#6b7151'; c.fillRect(-113, -213, 226, 94); c.strokeStyle = '#0e170f'; c.lineWidth = 12; c.strokeRect(-113, -213, 226, 94);
    text(c, 'CHANNEL', -90, -180, 17, '#1e291b', 'left', 'Georgia');
    for (let i = 0; i < 12; i++) line(c, [[-94 + i * 17, -160], [-94 + i * 17, i % 3 ? -141 : -134]], '#2a341f', 2);
    line(c, [[-70 + turn * 130, -168], [-70 + turn * 130, -128]], '#78352b', 4);
    for (let y = -76; y < 124; y += 14) { line(c, [[-110, y], [111, y]], '#111a13', 7); line(c, [[-107, y + 4], [108, y + 4]], '#64705545', 1); }
    c.save(); c.translate(72, 210); c.rotate(-1 + turn * 2); c.fillStyle = '#111a12'; c.beginPath(); c.arc(0, 0, 45, 0, 7); c.fill(); c.fillStyle = '#697354'; c.beginPath(); c.arc(0, 0, 34, 0, 7); c.fill(); for (let i = 0; i < 20; i++) { const a = i * Math.PI / 10; line(c, [[Math.cos(a) * 28, Math.sin(a) * 28], [Math.cos(a) * 34, Math.sin(a) * 34]], '#172215', 2); } line(c, [[0, -9], [0, -27]], '#d9bc7b', 4); c.restore();
    c.fillStyle = turn > .1 ? '#c48c40' : '#554b2a'; c.beginPath(); c.arc(-86, 197, 11, 0, 7); c.fill(); text(c, 'WALKIE TALKIE', -111, 160, 17, '#929a72', 'left', 'Georgia');
    [[-130,-260],[130,-260],[-130,265],[130,265]].forEach(p => screw(c, ...p)); c.restore();
  }
  function dice(c, x, y, angle = 0, size = 88) {
    c.save(); c.translate(x, y); c.rotate(angle); c.scale(size / 88, size / 88); shadow(c, 17, 12);
    const vertices = [[0,-95],[81,-42],[80,47],[0,94],[-81,46],[-81,-42]], mid = [0, -4];
    const fills = ['#aa673a','#77452b','#573523','#81472a','#a26135','#c18147'];
    vertices.forEach((p,i)=>{ path(c,[p,vertices[(i+1)%6],mid],true); c.fillStyle=fills[i];c.fill(); }); unshadow(c);
    c.strokeStyle = '#e0b16c'; c.lineWidth = 2; path(c, vertices, true); c.stroke(); vertices.forEach(p => line(c, [p, mid], '#d9a264a0', 1.5));
    text(c, '20', 0, 47, 39, '#f1d8a3', 'center', 'Georgia'); text(c, '8', -38, -15, 22, '#f1d8a3', 'center', 'Georgia'); text(c, '3', 39, -17, 22, '#f1d8a3', 'center', 'Georgia'); c.restore();
  }
  function candy(c, x, y, angle, color = '#a27139') { c.save(); c.translate(x,y); c.rotate(angle); shadow(c,12,7); path(c,[[-62,-12],[-104,-34],[-91,30],[-62,13]],true);c.fillStyle=color;c.fill();path(c,[[62,-12],[104,-34],[91,30],[62,13]],true);c.fill();rounded(c,-64,-27,128,54,5,color,'#c3a466');unshadow(c);line(c,[[-45,-25],[-45,25]],'#e6c58a66',2);line(c,[[46,-25],[46,25]],'#2b281e66',2);text(c,'31',0,10,27,'#e2ca91','center','Georgia');c.restore(); }
  function props(c, t, { mapProgress = .86, pen = false, radioTurn = .35, diceX = 370, diceY = 1280, diceA = -.2 } = {}) { c.drawImage(wood,0,0);map(c,mapProgress,pen);radio(c,780,1190,.91,radioTurn);dice(c,diceX,diceY,diceA);candy(c,850,1630,-.4);candy(c,260,1670,.24,'#655d38'); }
  function camera(c, zoom, x, y) { c.translate(W/2,H/2);c.scale(zoom,zoom);c.translate(-x,-y); }
  function underCaption(c) { const g=c.createLinearGradient(0,1320,0,1810);g.addColorStop(0,'#11131100');g.addColorStop(1,'#111311d9');c.fillStyle=g;c.fillRect(0,1320,W,600); }
  function caption(c, a, b, p = 1) { c.save();c.globalAlpha=ease(p);underCaption(c);text(c,a,108,1465,76);if(b)text(c,b,108,1553,76,C.orange);c.restore(); }
  function dust(c, t, red = false) { const rng=random(411);for(let i=0;i<45;i++){const x=(rng()*W+t*(8+rng()*15))%W,y=(rng()*H+t*(12+rng()*18))%H;c.fillStyle=red?'#b45b3a50':'#edcd8f20';c.beginPath();c.ellipse(x,y,1+rng()*2,1+rng()*4,.8,0,7);c.fill();} }
  const sources = { cover: 'assets/story-cover.webp', choices: 'assets/player-choices-mobile.png', input: 'assets/player-input-mobile.png', action: 'assets/player-action-excerpt.png', response: 'assets/player-response-excerpt.png' }, images = {};
  const ready = Promise.all(Object.entries(sources).map(([key, src]) => new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>{if(key==='cover'){images[key]=im;}else{const frozen=buffer(900,Math.round(900*im.height/im.width));const fc=frozen.getContext('2d',{willReadFrequently:true});fc.imageSmoothingQuality='high';fc.drawImage(im,0,0,frozen.width,frozen.height);const pixels=fc.getImageData(0,0,frozen.width,frozen.height);fc.putImageData(pixels,0,0);images[key]=frozen;}resolve();};im.onerror=()=>reject(new Error(`Missing image: ${src}`));im.src=src;}))).then(()=>document.fonts.load('600 80px YaHei','万圣夜别松手')).then(()=>document.fonts.ready);
  function cover(c,x,y,w,h) {const im=images.cover;if(!im)throw Error('Cover not ready');const scale=Math.max(w/im.width,h/im.height);const sw=w/scale,sh=h/scale;c.drawImage(im,(im.width-sw)/2,(im.height-sh)/2,sw,sh,x,y,w,h);}
  function photo(c,x,y,w,h,angle=0){c.save();c.translate(x,y);c.rotate(angle);shadow(c,28,17);c.fillStyle='#d3c6a0';c.fillRect(-w/2-17,-h/2-17,w+34,h+90);unshadow(c);cover(c,-w/2,-h/2,w,h);text(c,'OCTOBER 31, 1984',-w/2+15,h/2+47,24,'#5e5f44','left','Georgia');c.restore();}
  function torch(c,x,y,angle,t){c.save();c.translate(x,y);c.rotate(angle);const g=c.createLinearGradient(0,-100,0,-1100);g.addColorStop(0,'#e1bb6e60');g.addColorStop(1,'#e1bb6e00');path(c,[[-48,-80],[-420,-1300],[420,-1300],[48,-80]],true);c.fillStyle=g;c.fill();shadow(c,20,16);rounded(c,-42,-80,84,330,10,'#3e4b36','#7d8864');rounded(c,-65,-110,130,92,10,'#6c7858','#c1c09a');unshadow(c);for(let i=0;i<17;i++)line(c,[[-41,i*13+10],[41,i*13+10]],'#182719',4);c.fillStyle='#c9bb8d';c.fillRect(-18,-110,36,10);c.restore();}
  function cursor(c,x,y){c.save();c.translate(x,y);shadow(c,8,3);path(c,[[0,0],[0,76],[20,58],[38,96],[54,88],[35,51],[63,49]],true);c.fillStyle='#f3dfb7';c.fill();c.strokeStyle='#352f21';c.lineWidth=4;c.stroke();c.restore();}
  function uiBase(c){c.drawImage(wood,0,0);map(c,.87,false,-210,100,.06);radio(c,1050,1350,.65,.35);}

  const names = ['dice','radio','route','street','anomaly','torch','choice','player','input','return','enter'];
  function draw(c, id, t) {
    c.save(); c.setTransform(c.canvas.width/W,0,0,c.canvas.height/H,0,0);c.clearRect(0,0,W,H);
    const pulse=ease((t-.12)/.28);
    if(id==='dice'){
      c.save();camera(c,1.25,535,1040);props(c,t,{diceX:-200+ease(t/1.7)*790,diceY:740+ease(t/1.7)*360-Math.abs(Math.sin(Math.min(t,1.7)*7))*70*(1-clamp(t/1.7)),diceA:lerp(-6.5,.34,ease(t/1.7)),radioTurn:.05});c.restore();dust(c,t);
    } else if(id==='radio'){
      c.save();camera(c,lerp(1.15,1.52,pulse),720,1050);props(c,t,{radioTurn:lerp(.05,.77,ease((t-.3)/.8)),diceX:590,diceY:1100});c.restore();caption(c,'今晚只是讨糖',null,(t-.4)/.3);dust(c,t);
    } else if(id==='route'){
      const pan=ease((t-.1)/.3);c.save();camera(c,1.2,lerp(470,590,pan),850);props(c,t,{mapProgress:ease((t-.25)/2.5),pen:true,diceX:100,diceY:1440});c.restore();caption(c,'九点前回来',null,(t-.45)/.3);dust(c,t);
    } else if(id==='street'){
      const p=ease((t-.15)/.32);props(c,t);const w=lerp(640,1080,p),h=lerp(940,1920,p);photo(c,540,lerp(940,960,p),w,h,lerp(-.09,0,p));caption(c,'怪奇物语',null,(t-.6)/.3);dust(c,t);
    } else if(id==='anomaly'){
      props(c,t);const inspect=smooth((t-1.1)/.3)-smooth((t-2.7)/.3);photo(c,530+inspect*260,930-inspect*180,810+inspect*250,1240+inspect*300,.045-inspect*.28);const beam=c.createLinearGradient(0,100,1000,1700);beam.addColorStop(0,'#80282a00');beam.addColorStop(.6,'#80282a60');beam.addColorStop(1,'#80282a00');c.fillStyle=beam;c.fillRect(0,0,W,H);const k=.3+smooth((t-.15)/.6)*.7;c.save();c.translate(700,800);c.rotate(-.2);c.strokeStyle='#9a3b2a';c.lineWidth=6;c.beginPath();c.ellipse(0,0,125,75,0,-1.8,-1.8+k*5.3);c.stroke();c.restore();caption(c,'刚才有人叫我',null,(t-.25)/.3);text(c,'Will · 剧本片段',110,1360,32,'#c6b08a');dust(c,t,true);
    } else if(id==='torch'){
      const swing=-.95+1.3*smooth((t-.3)/.3)-.55*smooth((t-1.8)/.3);c.save();camera(c,1.08,lerp(550,475,pulse),970);props(c,t,{mapProgress:.9,radioTurn:.76});c.save();c.translate(800,1380);c.rotate(swing);c.beginPath();c.rect(-4000,-4000,8000,8000);c.moveTo(-55,-90);c.lineTo(-620,-2300);c.lineTo(620,-2300);c.lineTo(55,-90);c.closePath();c.fillStyle='#050805b8';c.fill('evenodd');c.restore();torch(c,800,1380,swing,t);c.restore();caption(c,'他看见了什么',null,(t-.45)/.3);dust(c,t);
    } else if(id==='choice'){
      c.save();camera(c,lerp(1.08,1.3,pulse),550,900);props(c,t,{mapProgress:.64,diceX:165,diceY:1350});const p=smooth((t-.35)/1.6);c.save();c.translate(105,325);c.rotate(-.09);c.setLineDash([7,7]);line(c,[[450,620],[450,620-220*p]],'#8c342a',5);line(c,[[450,620],[450+220*p,620]],'#8c342a',5);c.setLineDash([]);pencil(c,450+90*Math.sin(Math.min(t,2)*2.5),620-55*Math.sin(Math.min(t,2)*2.5),-.6);c.restore();c.restore();caption(c,'这次你来决定',null,(t-.45)/.3);dust(c,t);
    } else if(id==='player'){
      uiBase(c);text(c,'选择行动',108,268,88);text(c,'玩家界面实录 · 第 4 回合',110,335,32,'#c6b08a');const x=90,y=Math.round(390+lerp(100,0,pulse)),w=900,h=images.choices.height;shadow(c,30,18);c.drawImage(images.choices,x,y);unshadow(c);if(t>.6){c.globalAlpha=smooth((t-.6)/.3)*.85;c.strokeStyle=C.orange;c.lineWidth=5;c.strokeRect(x+8*w/365,y+275*w/365,343*w/365,96*w/365);c.globalAlpha=1;}dust(c,t);
    } else if(id==='input'){
      const proof=smooth((t-.6)/.3);uiBase(c);pencil(c,380,740,-1.1);text(c,t<.9?'也能自由行动':'故事会回应你',108,270,76);text(c,'玩家界面实录 · 已保存回合示例',110,335,32,'#c6b08a');const x=90,y=Math.round(775-60*pulse-250*proof);shadow(c,30,20);c.drawImage(images.input,x,y);unshadow(c);const a=ease((t-.3)/.4);cursor(c,lerp(1010,410,a),lerp(1500,lerp(830,580,proof),a));if(t>.6){c.save();c.translate((1-proof)*1200,0);text(c,'已保存的行动 · 节选',110,960,36,'#d8bd8b');c.drawImage(images.action,90,1000);text(c,'剧情回应 · 节选',110,1230,36,'#d8bd8b');c.drawImage(images.response,90,1270);c.restore();}dust(c,t);
    } else if(id==='return'){
      c.drawImage(wood,0,0);const land=ease(t/.5);c.save();c.translate((1-land)*1100,(1-land)*300);map(c,.9,false,0,0,lerp(-.4,-.06,land));c.save();c.translate(170,460);c.rotate(-.06);text(c,'怪奇物语',55,250,50,'#595d40');text(c,'万圣夜',48,385,110,'#343d30');text(c,'别松手',48,525,110,'#7f3028');text(c,'故事之间 / 互动同人故事',50,610,28,'#5c6145');c.restore();c.restore();radio(c,1040,1320,.7,.76);dice(c,lerp(1000,700,ease(t/1.3)),lerp(1350,1180,ease(t/1.3)),-2+ease(t/1.3)*2.5,96);candy(c,190,1600,.3);dust(c,t);
    } else if(id==='enter'){
      cover(c,0,0,W,H);const p=ease((t-.05)/.45);c.save();c.translate(-p*1450,-p*300);map(c,.9,false,0,0,-.06);dice(c,700,1180,.5,96);c.restore();caption(c,'故事之间','进入万圣夜',(t-.5)/.3);text(c,'打开平台 /play',110,1630,46,'#e9d9bb');text(c,'互动同人故事',110,1690,32,'#d4bd95');dust(c,t);
    } else throw Error(`Unknown scene: ${id}`);
    c.restore();
  }
  window.HawkinsPaint = { ready, draw, names };
})();
