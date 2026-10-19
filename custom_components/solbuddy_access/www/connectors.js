/* Wallet Standard discovery plus selected injected software-wallet providers. */
export function registry(scope = window) {
  const wallets = new Set();
  const api = Object.freeze({register(...items) {
    items.forEach(item => wallets.add(item));
    return () => items.forEach(item => wallets.delete(item));
  }});
  scope.addEventListener('wallet-standard:register-wallet', event => {
    if (typeof event.detail === 'function') event.detail(api);
  });
  scope.dispatchEvent(new CustomEvent('wallet-standard:app-ready', {detail: api}));
  return () => {
    const found = new Map();
    for (const wallet of wallets) {
      if (!['Phantom', 'Solflare', 'Trust', 'Trust Wallet'].includes(wallet.name)) continue;
      if (!wallet.features?.['standard:connect'] || !wallet.features?.['solana:signMessage']) continue;
      const name = wallet.name === 'Trust' ? 'Trust Wallet' : wallet.name;
      found.set(name, {name, async connect() {
        const result = await wallet.features['standard:connect'].connect();
        const account = result.accounts.find(a => a.chains?.includes('solana:mainnet') && a.features?.includes('solana:signMessage'));
        if (!account) throw new Error('This account cannot sign Solana mainnet messages.');
        return {address: account.address, async sign(message) {
          const bytes = new TextEncoder().encode(message);
          const results = await wallet.features['solana:signMessage'].signMessage({account, message: bytes});
          const proof = results[0];
          if (!proof || results.length !== 1 || proof.signature.length !== 64 || proof.signedMessage.length !== bytes.length || !bytes.every((b,i) => b === proof.signedMessage[i])) throw new Error('Wallet returned an unexpected message.');
          return Uint8Array.from(proof.signature);
        }};
      }});
    }
    for (const [name, provider] of [['Phantom', scope.phantom?.solana], ['Solflare', scope.solflare], ['Trust Wallet', scope.trustwallet?.solana]]) {
      if (found.has(name) || typeof provider?.connect !== 'function' || typeof provider?.signMessage !== 'function') continue;
      found.set(name, {name, async connect() {
        await provider.connect();
        const address = provider.publicKey?.toString();
        if (!address) throw new Error('No Solana account selected.');
        return {address, async sign(message) {
          if (provider.publicKey?.toString() !== address) throw new Error('Wallet account changed.');
          const response = await provider.signMessage(new TextEncoder().encode(message), 'utf8');
          const signature = response?.signature ?? response;
          if (!(signature instanceof Uint8Array) || signature.length !== 64) throw new Error('Wallet signing is unsupported.');
          if (response?.publicKey && response.publicKey.toString() !== address) throw new Error('Wallet account changed.');
          return signature;
        }};
      }});
    }
    return [...found.values()];
  };
}
