// Only system-owned fields may be translated. Names, reasons, addresses and codes stay intact.
import {knownText} from './locale-en.mjs?v=20261125results';
const systemFields=new Set(['جهت','علت ثبت','رسید پیوست','ثبت در کیف پول','مرحله بعد','قانون','شماره‌خوان','ساختار کارت']);
export function fieldValue(field) {
 if(field.label==='تأیید شبکه')return String(field.value).replace(/^(\d+) از (\d+)$/, '$1 of $2');
 return systemFields.has(field.label)?knownText(field.value):String(field.value??'');
}
export function notificationBody(item) {
 const body=String(item.body??'');
 if(['deposit','withdraw'].includes(item.kind))return body.replace(/^درخواست #(\d+) \| مبلغ ([\d,]+) تومان$/, 'Request #$1 | Amount $2 toman');
 if(item.kind==='crypto')return body.replace(/^فاکتور #(\d+) \| ([\d,]+) تومان \| /,'Invoice #$1 | $2 toman | ');
 if(['win','admin_message'].includes(item.kind)){
  const m=/^([^|]+) \| مبلغ (-?[\d,]+) تومان$/.exec(body);
  if(m)return `${knownText(m[1])} | Amount ${m[2]} toman`;
 }
 return knownText(body);
}
