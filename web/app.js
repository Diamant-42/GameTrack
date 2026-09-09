let data={games:[],active:[],total:0,today:0};let chart,chart2;

const $=id=>document.getElementById(id);
function fmt(sec){sec=Math.max(0,Math.floor(sec));let h=Math.floor(sec/3600),m=Math.floor(sec%3600/60);return `${h}h ${String(m).padStart(2,"0")}m`}
function nav(page){document.querySelectorAll(".page").forEach(x=>x.classList.remove("active"));$(page).classList.add("active");document.querySelectorAll(".nav").forEach(x=>x.classList.toggle("active",x.dataset.page===page));$("crumb").textContent={dashboard:"Accueil",games:"Jeux",stats:"Statistiques",sessions:"Sessions",settings:"Paramètres"}[page];$("sidebar").classList.remove("open");if(page==="sessions")loadSessions()}

async function refresh(){
 const r=await fetch("/api/games");data=await r.json();
 $("total").textContent=fmt(data.total);$("today").textContent=fmt(data.today);$("count").textContent=data.games.length;
 $("sessions").textContent=data.games.reduce((a,g)=>a+Number(g.sessions),0);
 $("stotal").textContent=fmt(data.total);
 $("best").textContent=data.games[0]?.name||"—";
 renderTop();renderGames();renderCharts();renderActive();
}
function renderActive(){
 const g=data.active[0];
 if(!g){$("current").classList.add("hidden");$("live").textContent="● Aucun jeu en cours";return}
 $("current").classList.remove("hidden");$("current").innerHTML=`${g.icon} <b>${g.name}</b> · ${fmt(g.elapsed)}`;
 $("live").textContent=`● ${g.name} en cours · ${fmt(g.elapsed)}`;
}
function renderTop(){
 const max=Math.max(1,...data.games.map(g=>Number(g.seconds)));
 $("top").innerHTML=data.games.slice(0,5).map(g=>`<div class="game-row"><div class="game-logo">${g.icon}</div><div><b>${esc(g.name)}</b><small>${g.sessions} sessions</small><div class="bar"><i style="width:${g.seconds/max*100}%"></i></div></div><span class="hours">${fmt(g.seconds)}</span></div>`).join("")||"<p style='color:#697183;font-size:10px'>Aucun jeu suivi.</p>";
}
function renderGames(){
 const q=($("search")?.value||"").toLowerCase();const max=Math.max(1,...data.games.map(g=>Number(g.seconds)));
 $("gamesGrid").innerHTML=data.games.filter(g=>g.name.toLowerCase().includes(q)).map(g=>`<article class="game-card"><div class="game-logo">${g.icon}</div><h3>${esc(g.name)}</h3><p>${g.process_name} · ${g.sessions} sessions</p><div class="bar"><i style="width:${g.seconds/max*100}%"></i></div><p style="margin-top:8px">${fmt(g.seconds)}</p><button onclick="removeGame(${g.id})">Supprimer</button></article>`).join("")||"<p style='color:#697183'>Aucun jeu trouvé.</p>";
}
function renderCharts(){
 const labels=data.games.slice(0,7).map(g=>g.name),values=data.games.slice(0,7).map(g=>Math.round(g.seconds/3600*10)/10);
 if(chart)chart.destroy();chart=new Chart($("chart"),{type:"line",data:{labels:["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"],datasets:[{data:[0,0,0,0,0,0,0],borderColor:"#7865ff",backgroundColor:"rgba(120,101,255,.08)",fill:true,tension:.4,borderWidth:2}]},options:{plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:"#657083",font:{size:9}}},y:{beginAtZero:true,grid:{color:"rgba(100,110,130,.12)"},ticks:{color:"#657083",font:{size:9}}}}}});
 if(chart2)chart2.destroy();chart2=new Chart($("chart2"),{type:"doughnut",data:{labels,datasets:[{data:values,backgroundColor:["#7865ff","#5e8cff","#48df91","#ffb65e","#ff6f83","#6f7b91","#9c7aff"],borderWidth:0}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:"#a8afbd",font:{size:10}}}}}});
}
async function loadSessions(){
 const r=await fetch("/api/games");const d=await r.json();
 $("sessionList").innerHTML="<p style='color:#697183;font-size:10px'>Les sessions sont enregistrées dans SQLite. Le détail historique sera affiché ici dans la prochaine version.</p>";
}
function esc(s){return String(s).replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]))}
function openAdd(){$("addModal").classList.remove("hidden");$("step1").classList.remove("hidden");$("step2").classList.add("hidden");$("error").textContent=""}
function closeAdd(){$("addModal").classList.add("hidden")}
async function loadProcesses(){
 $("error").textContent="";const r=await fetch("/api/processes");const ps=await r.json();
 const select=$("process");select.innerHTML="";
 ps.sort((a,b)=>a.name.localeCompare(b.name)).forEach(p=>{const o=document.createElement("option");o.value=JSON.stringify({name:p.name,pid:p.pid});o.textContent=`${p.name}  (PID ${p.pid})`;select.appendChild(o)});
 if(!ps.length){$("error").textContent="Aucun processus détecté.";return}
 $("step1").classList.add("hidden");$("step2").classList.remove("hidden");
}
async function saveGame(){
 const name=$("gameName").value.trim(),selected=$("process").value,icon=$("gameIcon").value;
 let process_name,process_pid;
 try{({name:process_name,pid:process_pid}=JSON.parse(selected))}catch{process_name=selected;process_pid=null}
 if(!name){$("error").textContent="Donne un nom au jeu.";return}
 const r=await fetch("/api/games",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({name,process_name,process_pid,icon})});
 const j=await r.json();if(!r.ok){$("error").textContent=j.error||"Erreur.";return}closeAdd();$("gameName").value="";await refresh();nav("games");
}
async function removeGame(id){if(!confirm("Supprimer ce jeu et son historique ?"))return;await fetch(`/api/games/${id}`,{method:"DELETE"});refresh()}
document.querySelectorAll(".nav").forEach(b=>b.addEventListener("click",()=>nav(b.dataset.page)));
$("menu").addEventListener("click",()=>$("sidebar").classList.toggle("open"));
$("search").addEventListener("input",renderGames);
refresh();setInterval(refresh,3000);

