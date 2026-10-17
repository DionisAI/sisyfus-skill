"""Independent frozen in-flight proof with an observed end-of-scenario marker.

The original harness is unchanged. Later readonly inventory calls receive real
public-shaped replies rather than leaving a second unresolved fixture Promise.
An early Node exit never qualifies as a completed protocol regression.
"""
import json
import subprocess

from sisyfus.workers.lead_chat_page import PAGE
from test_chat_node_placement_page import HARNESS


def test_inflight_inventory_refresh_settles_before_claiming_start_proof():
    case = r'''
const complete={chats:[],issues:[],auto_start:false};
setGet(call=>call.path==='/api/chats'?complete:undefined);
await inventory();await selectMission(mid);assert.equal(el('mission-start').disabled,false);
let release,reads=0;
setGet(call=>call.path==='/api/chats'?(++reads===1?new Promise(resolve=>{release=resolve;}):complete):undefined);
const refreshing=inventory();for(let i=0;i<8;i++)await Promise.resolve();render();
const disabled=el('mission-start').disabled;
setPost(()=>response({accepted:true}));await el('mission-start').click();
el('mission-permission').checked=true;const submitted=el('mission-confirm').onsubmit({preventDefault(){}});
for(let i=0;i<8;i++)await Promise.resolve();
release(complete);await refreshing;await submitted;await readSelected();
assert.equal(disabled,true);assert.equal(calls.filter(call=>call.method==='POST').length,0);
assert.equal(el('mission-start').disabled,false);assert.equal(snapshot.snapshot.all_verified,false);
console.log('inventory-refresh-scenario-completed');
'''
    script = PAGE.split('<script nonce="NONCE">', 1)[1].split('</script>', 1)[0]
    script = script.rsplit('render(); resizeComposer();', 1)[0]
    result = subprocess.run(['node', '-e', HARNESS.replace('SOURCE', json.dumps(script)).replace('CASE', json.dumps(case))],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
    assert 'inventory-refresh-scenario-completed' in result.stdout, 'scenario did not settle: ' + result.stdout + result.stderr
