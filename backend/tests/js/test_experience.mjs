import assert from "node:assert/strict";
import { prizeRows, personalPrize, prizeLabel, ruleLabel, inboxItems, filterInbox } from "../../app/static/mini/experience.mjs";

const shared = { winner_user_ids:[8,8,9], winner_card_ids:[101,102,103], amounts_by_card:[30,40,50], amount_total:120 };
assert.equal(personalPrize(shared,8),70,"repeated owners must retain both card shares");
assert.equal(personalPrize(shared,9),50);
assert.equal(personalPrize(shared,10),null);
assert.equal(personalPrize({amount_total:120,winner_user_ids:[8,9]},8),null,"never use event total as a personal amount");
assert.equal(personalPrize({...shared,amounts_by_card:[30,40]},8),null);
assert.equal(personalPrize({...shared,winner_card_ids:[101,101,103]},8),null);
assert.equal(personalPrize({...shared,amount_total:121},8),null);
assert.equal(personalPrize({...shared,amounts_by_card:[30,-1,91]},8),null);
assert.equal(personalPrize({...shared,amounts_by_card:[30,null,90]},8),null);
assert.equal(personalPrize({...shared,amounts_by_card:[30,40,Infinity]},8),null);
assert.equal(personalPrize({...shared,winner_users:[{user_id:9,card_id:101,amount:120}]},8),null);
assert.equal(personalPrize({winner_users:[{user_id:8,card_id:100,amount:0}]},8),0);
assert.equal(prizeRows(shared).length,3);
for (const invalid of [true,false,[],[1],{}," ","0x10"]) {
  assert.equal(prizeRows({winner_user_ids:[8],winner_card_ids:[101],amounts_by_card:[invalid]}).length,0);
  assert.equal(prizeRows({winner_user_ids:[invalid],winner_card_ids:[101],amounts_by_card:[1]}).length,0);
  assert.equal(prizeRows({winner_user_ids:[8],winner_card_ids:[invalid],amounts_by_card:[1]}).length,0);
}
assert.match(ruleLabel("LEGACY",true),/ناسازگار/);
for (const [rule,layout] of [["LINE",2],["FULL_CARD",2],["LEGACY",1]]) assert.ok(!ruleLabel(rule,layout).includes("ناسازگار"));
assert.match(ruleLabel("LINE",1),/ناسازگار/);
assert.match(prizeLabel("PRIZE_COL",{game_rule:"FULL_CARD",card_layout_version:2}),/ناسازگار/);
assert.match(prizeLabel("PRIZE_ROW",{game_rule:"FULL_CARD",card_layout_version:2}),/پرکردنی/);
assert.match(prizeLabel("PRIZE_COL",{game_rule:"LINE",card_layout_version:2}),/۳ عدد/);
assert.match(prizeLabel("PRIZE_ROW",{}),/قابل تأیید نیست/);
const items=inboxItems([{id:"p:1",kind:"deposit"},{id:"p:1",kind:"deposit"},{id:"w:1",kind:"win"}], [{id:91,status:"LOBBY",game_rule:"LINE",card_layout_version:2}]);
assert.equal(items.length,3);
assert.equal(filterInbox(items,"game",new Set()).length,1);
assert.equal(filterInbox(items,"payment",new Set()).length,1);
assert.equal(filterInbox(items,"unread",new Set(["p:1"])).length,2);
console.log("PASS: verified personal prizes, repeated owners, invalid payloads, rules and inbox filters");
