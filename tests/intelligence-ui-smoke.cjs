/* Visual regression smoke: DOM and SVG charts with deterministic mocked API data. */
const fs = require("node:fs");
const assert = require("node:assert/strict");
const { JSDOM } = require("jsdom");

function makeAnalytics(days) {
  const daily = [];
  for(let i=0;i<days;i++){
    const d=new Date("2026-10-01T12:00:00Z");d.setUTCDate(d.getUTCDate()+i);
    const n=(i+1)*3200;
    daily.push({date:d.toISOString().slice(0,10),tokens:n,input_tokens:2000,output_tokens:1200,cached_tokens:500,events:2,sessions:1});
  }
  return {source:"DEMO SIMULADA",mode:"DEMO (simulado)",generated_at:new Date().toISOString(),days,
    coverage:{files_scanned:0,partial:false},summary:{tokens:daily.reduce((a,x)=>a+x.tokens,0),sessions:3,projects:2,events:40},
    daily,calendar:daily,
    hours:Array.from({length:168},(_,i)=>({weekday:Math.floor(i/24),hour:i%24,tokens:(i+1)*100,events:1})),
    models:[{name:"gpt-demo",tokens:100000}],projects:[{name:"project-demo",tokens:100000}]};
}
function makeResponse(v){return {ok:true,json:async()=>v};}
function wait(ms){return new Promise(resolve=>setTimeout(resolve,ms));}

async function main(){
  const errors=[];
  const html=fs.readFileSync("control_center/static/intelligence.html","utf8");
  const dom=new JSDOM(html,{url:"http://127.0.0.1:8765/intelligence",runScripts:"dangerously",pretendToBeVisual:true,
    beforeParse(window) {
      window.addEventListener("error",e=>errors.push(e.message));
      window.fetch=async url=>{
        if(url.startsWith("/api/intelligence?")){
          const days=Number(new URL(url,"http://localhost").searchParams.get("days"));
          return makeResponse(makeAnalytics(days));
        }
        if(url==="/api/status")return makeResponse({activity_counts:{active:1,recent:2,historical:1},
          sessions:[{session_id:"session-abcd",project:"SWAT",percent_approx:76.2,activity_category:"active"}]});
        if(url==="/api/codex/account")return makeResponse({account:{plan:"pro"},
          rate_limits:[{window_duration_mins:300,used_percent:20,remaining_percent:80}]});
        if(url==="/api/intelligence/windows-providers")return makeResponse({available:true,
          providers:[{provider:"codex",status:"operational",windows:[
            {name:"Principal",remaining_percent:50,used_percent:50,window_minutes:300}]}]});
        if(url==="/api/intelligence/ccusage")return makeResponse({available:true,
          daily:[{date:"2026-11-01",tokens:4000,cost_usd:0.2}],
          agents:[{name:"claude",tokens:4000}],
          models:[{name:"claude-demo",cost_usd:0.2,unpriced:false}],unpriced_models:[]});
        throw new Error("Unexpected URL "+url);
      };
    }});
  try{
    const doc=dom.window.document;
    for(let i=0;i<30 && doc.querySelectorAll("#calendar .cell:not(.blank)").length!==90;i++)await wait(25);
    assert.deepEqual(errors,[]);
    assert.equal(doc.querySelectorAll("#calendar .cell:not(.blank)").length,90);
    assert.equal(doc.querySelectorAll("#hour-chart .hour-cell").length,168);
    assert.ok(doc.querySelector("#daily-chart svg"));
    assert.ok(doc.querySelector("#composition-chart svg"));
    assert.ok(doc.querySelectorAll("#models-chart .bar-row").length>0);
    assert.ok(doc.querySelectorAll("#weekly-chart .bar-row").length>0);
    assert.ok(doc.querySelectorAll("#context-chart .bar-row").length>0);

    doc.querySelector('[data-days="30"]').click();
    for(let i=0;i<30 && doc.querySelectorAll("#calendar .cell:not(.blank)").length!==30;i++)await wait(25);
    assert.equal(doc.querySelectorAll("#calendar .cell:not(.blank)").length,30);

    doc.getElementById("quota-btn").click();await wait(40);
    assert.ok(doc.getElementById("quotas").textContent.includes("80% restante"));
    doc.getElementById("providers-btn").click();await wait(40);
    assert.ok(doc.getElementById("providers-chart").textContent.includes("codex"));
    doc.getElementById("ccusage-btn").click();await wait(40);
    assert.ok(doc.querySelector("#external-cost-chart svg"));
    assert.ok(doc.getElementById("external-agents-chart").textContent.includes("claude"));
    assert.deepEqual(errors,[]);
    process.stdout.write("INTELLIGENCE_UI_SMOKE=PASS\n");
  }finally{dom.window.close();}
}
main().catch(e=>{console.error(e);process.exitCode=1;});
