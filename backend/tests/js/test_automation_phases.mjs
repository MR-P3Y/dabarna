import assert from 'node:assert/strict';
import {automationClock} from '../../app/static/mini/automation-clocks.mjs';
const now=Date.parse('2026-11-13T12:00:00Z');
for(const phase of ['START','NEXT_NUMBER','NEXT_GAME']) {
 const item={level:'LOW',phase,deadline_utc:'2026-11-13T12:00:03Z',duration_seconds:3};
 assert.equal(automationClock(item,now,now).seconds,3);
 assert.equal(automationClock(item,now+4000,now).seconds,0);
 assert.equal(automationClock(item,now+4000,now).pending,true);
 assert.match(automationClock(item,now+4000,now).label,/در انتظار تأیید سرور/);
 assert.equal(automationClock(item,now+16000,now).seconds,null,'stale data cannot pretend the next cycle began');
 assert.equal(automationClock({...item,deadline_utc:null},now,now).seconds,null);
}
for(const phase of ['WAITING_PLAYERS','PAUSED','MANUAL_START','MANUAL_DRAW','NOT_READY','MISSING_END_TIME']) {
 assert.equal(automationClock({level:'HIGH',phase},now,now).seconds,null);
}
assert.equal(automationClock({level:'unknown',phase:'START'},now,now),null);
console.log('PASS: server-owned start, next-number and next-game clocks; delay, pause and stale states.');
