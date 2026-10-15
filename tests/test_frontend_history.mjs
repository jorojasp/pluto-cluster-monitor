import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";

const source = fs.readFileSync(new URL("../src/pluto_monitor/web/static/app.js", import.meta.url), "utf8");
new vm.Script(source);
const globalBlock = source.slice(source.indexOf("const powerHistory ="), source.indexOf("function colorForGroup"));
const resetBlock = source.slice(source.indexOf("function resetHistory("), source.indexOf("function renderConnectedRadios("));
const historyBlock = source.slice(source.indexOf("function pushHistory("), source.indexOf("function renderLegend("));
const context = vm.createContext({ colorForGroup: () => "#56B4E9" });
vm.runInContext("const MAX_HISTORY_POINTS = 120;" + globalBlock + resetBlock + historyBlock, context);
function run(code) { return vm.runInContext(code, context); }
run('updateHistories({session_id:"one",groups:{A:{sequence:1,timestamp:10,mean_power_db:1,mean_noise_db:0}}})');
run('updateHistories({session_id:"one",groups:{A:{sequence:1,timestamp:10,mean_power_db:1,mean_noise_db:0}}})');
assert.equal(run("powerHistory.A.length"), 1, "Duplicate WebSocket pushes must not add samples");
run('updateHistories({session_id:"one",groups:{A:{sequence:1,timestamp:10,mean_power_db:1,mean_noise_db:0},B:{sequence:1,timestamp:10.2,mean_power_db:2,mean_noise_db:null}}})');
assert.equal(run("powerHistory.A.length"), 1);
assert.equal(run("powerHistory.B.length"), 1);
assert.equal(run("noiseHistory.B[0].value"), null, "Invalid estimates must create gaps");
assert.ok(Math.abs(run("powerHistory.B[0].t") - 0.2) < 1e-8);
run('updateHistories({session_id:"two",groups:{A:{sequence:1,timestamp:20,mean_power_db:5,mean_noise_db:1}}})');
assert.equal(run("powerHistory.A.length"), 1);
assert.equal(run("Object.keys(powerHistory).length"), 1, "New session clears old groups");
const labels = [];
const ctx = { clearRect(){}, fillText(text){ labels.push(text); }, beginPath(){},
              moveTo(){}, lineTo(){}, stroke(){}, arc(){}, fill(){} };
context.canvas = {id:"power",width:600,height:220,getContext:()=>ctx};
run("drawChart(canvas,powerHistory)");
assert.ok(labels.includes("Elapsed time (s)"));
assert.ok(run('chartRanges.get("power").max-chartRanges.get("power").min') >= 20);
console.log("PASS: frontend syntax, deduplication per group, timestamps, null gaps, session reset and chart axes");
