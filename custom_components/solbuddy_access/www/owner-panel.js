// Native HA panel: HA supplies its authenticated API client; no token input/storage.
class SolbuddyOwnerPanel extends HTMLElement {
  set hass(value) {
    this._hass = value;
    if (!this.ready) {this.ready = true; this.render(); this.refresh().catch(e => this.error(e));}
  }
  disconnectedCallback() {if (this.root) this.$('invitation').value = '';}
  $(id) {return this.root.getElementById(id);}
  async api(operation, payload = {}) {
    return this._hass.callApi('POST', 'solbuddy_access/v1/wallet/owner', {operation, payload});
  }
  error(e) {this.$('status').textContent = e?.body?.error || e?.message || 'Request denied. Only the Home Assistant owner can manage access.';}
  render() {
    this.root = this.attachShadow({mode:'open'});
    this.root.innerHTML = `<style>
      :host{display:block;font-family:var(--paper-font-body1_-_font-family,system-ui,sans-serif);color:var(--primary-text-color,#172b3a);padding:24px;max-width:850px;margin:auto}h1{font-size:28px}section{border:1px solid var(--divider-color,#d2dce3);border-radius:12px;padding:20px;margin:20px 0}label{display:block;margin:12px 0}input,select,textarea{box-sizing:border-box;display:block;width:100%;padding:10px;margin-top:5px;color:var(--primary-text-color,#172b3a);background:var(--card-background-color,#fff);border:1px solid var(--divider-color,#d2dce3);border-radius:6px}button{padding:10px 16px;margin:8px 8px 0 0;cursor:pointer}a{color:var(--primary-color,#007fa3)}.actions label{display:inline-block;margin-right:24px}.actions input{display:inline;width:auto}textarea{min-height:70px}#status{white-space:pre-wrap}
      </style><h1>SOLBUDDY Access</h1><p>Approve a wallet, select a light and actions, and set how long access lasts. Your existing Home Assistant login is used.</p>
      <p id="enabled"></p><a href="/config/integrations/integration/solbuddy_access">Configure guest and wallet access</a>
      <p id="connection"></p><a id="guest" target="_blank" rel="noopener noreferrer" hidden>Open guest wallet page</a>
      <section><h2>Create temporary access</h2>
      <label>Guest name<input id="name" maxlength="100" autocomplete="off"></label>
      <label>Approved Solana wallet<input id="wallet" autocomplete="off" spellcheck="false"></label>
      <label>Supported light<select id="entity"></select></label><p id="devices"></p>
      <div class="actions"><label><input id="on" type="checkbox" checked>Turn on</label><label><input id="off" type="checkbox" checked>Turn off</label></div>
      <label>Duration in minutes (1–43200)<input id="minutes" type="number" value="60" min="1" max="43200"></label>
      <button id="create">Approve and create access</button></section>
      <section><h2>Existing grants</h2><button id="refresh">Refresh</button><label>Grant<select id="grants"></select></label><p id="grantDetails"></p>
      <button id="issue">Generate invitation</button><button id="revoke">Revoke access</button>
      <label>Invitation — share privately; expires in five minutes<textarea id="invitation" readonly autocomplete="off"></textarea></label>
      <button id="clear">Clear invitation</button></section><p id="status" role="status"></p>`;
    this.$('grants').onchange = () => this.applyState();
    for (const id of ['create','refresh','issue','revoke','clear']) this.$(id).onclick = async () => {
      this.root.querySelectorAll('button').forEach(b=>b.disabled=true);
      try {await this[id]();} catch(e) {this.error(e);}
      finally {this.root.querySelectorAll('button').forEach(b=>b.disabled=false); this.applyState();}
    };
  }
  applyState() {
    const enabled = this.state?.guest_enabled && this.state?.wallet_enabled;
    this.$('create').disabled = !enabled || !this.state.entities.length;
    this.$('issue').disabled = !enabled || !this.$('grants').value;
    this.$('revoke').disabled = !this.$('grants').value;
    const selected = this.grants?.find(g=>g.grant_id===this.$('grants').value);
    this.$('grantDetails').textContent = selected ? 'Approved wallet: '+(selected.wallet_address || 'Invitation-only grant') : '';
  }
  async refresh() {
    this.state = await this.api('status');
    const s = this.state;
    this.$('enabled').textContent = `Guest access: ${s.guest_enabled ? 'enabled' : 'disabled'}. Wallet access: ${s.wallet_enabled ? 'enabled' : 'disabled'}.`;
    this.$('connection').textContent = s.https_origin ? `Wallet signing uses ${s.https_origin}. Guest controls also work on your local HA address.` : 'Open this SOLBUDDY panel once through your existing HTTPS Home Assistant address to discover the wallet signing URL.';
    this.$('guest').hidden = !s.https_origin;
    if (s.https_origin) this.$('guest').href = s.https_origin + '/api/solbuddy_access/v1/wallet/ui';
    this.$('entity').replaceChildren(...s.entities.map(e=>new Option(e.name+' ('+e.entity_id+')',e.entity_id)));
    this.$('devices').textContent = s.entities.length ? 'Only reviewed physical lights are listed.' : 'No supported lights found. This build supports individual Hue v2 lights; switches and other device integrations are not yet supported.';
    await this.list(); this.applyState();
  }
  async list() {
    const {grants} = await this.api('list'); this.grants=grants;
    this.$('grants').replaceChildren(...grants.map(g=>new Option(`${g.guest_display_name} · ${g.status} · expires ${g.expires_at}`,g.grant_id)));
  }
  async create() {
    const minutes = Number(this.$('minutes').value);
    if (!Number.isInteger(minutes) || minutes < 1 || minutes > 43200) throw new Error('Choose a duration from 1 to 43200 minutes.');
    const actions = ['on','off'].filter(id=>this.$(id).checked).map(id=>'turn_'+id);
    if (!actions.length) throw new Error('Choose at least one action.');
    const wallet = this.$('wallet').value.trim(), entity = this.$('entity').value;
    if (!confirm(`Approve wallet ${wallet}\nfor ${entity}: ${actions.join(', ')}\nfor ${minutes} minutes?`)) return;
    const now = Date.now();
    const grant = await this.api('create',{guest_display_name:this.$('name').value.trim(),wallet_address:wallet,starts_at:new Date(now).toISOString(),expires_at:new Date(now+minutes*60000).toISOString(),policies:[{entity_id:entity,actions}]});
    await this.list(); this.$('grants').value=grant.grant_id; this.$('status').textContent='Access approved. Generate an invitation for the guest.';
  }
  async issue() {
    const result = await this._hass.callApi('POST','solbuddy_access/v1/invitations',{grant_id:this.$('grants').value});
    this.$('invitation').value=result.invitation; this.$('status').textContent='Invitation expires: '+result.expires_at;
  }
  async revoke() {await this.api('revoke',{grant_id:this.$('grants').value});this.clear();await this.list();this.$('status').textContent='Access revoked.';}
  clear() {this.$('invitation').value='';}
}
if (!customElements.get('solbuddy-owner-panel')) customElements.define('solbuddy-owner-panel', SolbuddyOwnerPanel);
