// Render only the small, typed observation-age response; never provider text.
function duration(seconds) {
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor(seconds % 86400 / 3600);
  const minutes = Math.floor(seconds % 3600 / 60);
  const remainder = seconds % 60;
  return [[days,'d'],[hours,'h'],[minutes,'m'],[remainder,'s']].filter(([n])=>n).map(([n,u])=>`${n}${u}`).join(' ') || '0s';
}
export function freshnessMessage(result) {
  if (result?.error !== 'eligibility_stale') return null;
  const messages = [];
  for (const [key,label,limit] of [['price','Price',300],['balance','Balance',60]]) {
    const value = result.observations?.[key];
    if (!value || !Number.isSafeInteger(value.age_seconds) || value.max_age_seconds !== limit) continue;
    const age = value.age_seconds;
    if (value.status === 'stale' && age > limit) messages.push(`${label} observation is stale: ${duration(age)} old (maximum ${duration(limit)}).`);
    else if (value.status === 'future' && age < 0) messages.push(`${label} observation is ${duration(-age)} ahead of the server clock; future observations are rejected.`);
  }
  return messages.length ? messages.join(' ') + ' No new session was issued. The $2 SBUD requirement is unchanged.' : null;
}
