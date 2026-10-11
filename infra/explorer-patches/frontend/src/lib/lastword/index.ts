/**
 * LASTWORD knowledge shared by the server and the browser: who is who on the chain,
 * how to read a LASTWORD call, and how to format the money.
 */
import { Interface, getAddress } from 'ethers';

export const CONTRACT = getAddress('0xc5a5c42992decbae36851359345fe25997f5c42d');
export const TOKEN = { address: getAddress('0x09635F643e140090A9A8Dcd712eD6285858ceBef'), symbol: 'dUSD', decimals: 6 };

export type Party = { name: string; kind: 'supplier' | 'role' | 'contract' | 'token'; detail?: string; suspended?: boolean };

/** Address book: suppliers come from the agent's whitelist (agent/demo/whitelist.json). */
const BOOK: Record<string, Party> = {
	[CONTRACT]: { name: 'LASTWORD contract', kind: 'contract', detail: 'the only payment authority' },
	[TOKEN.address]: { name: 'dUSD stablecoin', kind: 'token', detail: 'demo stablecoin, 6 decimals' },
	'0x70997970C51812dc3A010C7d01b50e0d17dc79C8': { name: 'AI agent', kind: 'role', detail: 'can only propose' },
	'0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC': { name: 'Bridge (gas only)', kind: 'role', detail: 'submits badge signatures, approves nothing' },
	'0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266': { name: 'Treasury vault · admin', kind: 'role', detail: 'holds the funds; whitelist after timelock' },
	'0x1111111111111111111111111111111111111111': { name: 'ACME Steel Supplies', kind: 'supplier', detail: 'whitelisted · cap 1,000 dUSD' },
	'0x2222222222222222222222222222222222222222': { name: 'Port Logistics', kind: 'supplier', detail: 'whitelisted · cap 500 dUSD' },
	'0x3333333333333333333333333333333333333333': { name: 'Rhine Valley Castings GmbH', kind: 'supplier', detail: 'whitelisted · cap 750 dUSD' },
	'0x4444444444444444444444444444444444444444': { name: 'Nordwind Fasteners AB', kind: 'supplier', detail: 'whitelisted · cap 300 dUSD' },
	'0x5555555555555555555555555555555555555555': { name: 'Meridian Freight Partners', kind: 'supplier', detail: 'whitelisted · cap 600 dUSD' },
	'0x6666666666666666666666666666666666666666': { name: 'Atlas Precision Tools Inc', kind: 'supplier', detail: 'whitelisted · cap 1,000 dUSD' },
	'0x7777777777777777777777777777777777777777': { name: 'Sahel Minerals Trading', kind: 'supplier', detail: 'SUSPENDED', suspended: true }
};

export function party(addr?: string | null): Party | null {
	if (!addr) return null;
	try {
		return BOOK[getAddress(addr)] ?? null;
	} catch {
		return null;
	}
}

export const ABI = [
	'function propose(bytes intent, bytes proofs) returns (uint32)',
	'function attestDelivery(uint32 reqId, bytes stockIntent, bytes32 r, bytes32 s)',
	'function approve(uint32 reqId, bytes dafIntent, bytes32 r, bytes32 s)',
	'function cancel(uint32 reqId)',
	'function anchor(bytes32 root)',
	'function pause()',
	'function unpause()',
	'function proposeWhitelist(address supplier, uint64 cap, bool active)',
	'function applyWhitelist(address supplier)',
	'function registerDafKey(bytes32 qx, bytes32 qy)',
	'function registerStockKey(bytes32 qx, bytes32 qy)',
	'function registerDuressKey(bytes32 qx, bytes32 qy)',
	'event Proposed(uint32 indexed reqId, bytes32 digest)',
	'event Attested(uint32 indexed reqId)',
	'event Approved(uint32 indexed reqId, address beneficiary, uint256 amount)',
	'event Refused(uint32 indexed reqId, uint8 reason)',
	'event Cancelled(uint32 indexed reqId)',
	'event Anchored(bytes32 root)',
	'event Paused()',
	'event Unpaused()',
	'event WhitelistProposed(address indexed supplier, uint64 cap, bool active, uint64 readyAt)',
	'event WhitelistApplied(address indexed supplier, uint64 cap, bool active)',
	'event Transfer(address indexed from, address indexed to, uint256 value)'
];
export const IFACE = new Interface(ABI);

/** Human titles for each contract function, in the order a payment goes through them. */
export const ACTIONS: Record<string, { title: string; step?: number; who: string; meaning: string }> = {
	propose: { title: 'Payment proposed', step: 1, who: 'AI agent', meaning: 'The agent read the quote and asked for a payment. The contract checked the hard criteria (C1 C3 C6 C8 C9) and stored the intent digest.' },
	attestDelivery: { title: 'Delivery attested', step: 2, who: 'Badge · STOCK role', meaning: 'The STOCK role confirmed delivery on the hardware badge (PIN on the keypad). The contract verified the P-256 signature of the TROPIC01 key.' },
	approve: { title: 'Payment approved & paid', step: 3, who: 'Badge · DAF role', meaning: 'The DAF read beneficiary and amount on the badge screen and signed with the PIN. The contract verified the signature on the digest it recomputed, then paid.' },
	cancel: { title: 'Payment cancelled', who: 'admin', meaning: 'The request was cancelled before execution.' },
	anchor: { title: 'Journal anchored', who: 'bridge', meaning: 'The Merkle root of the evidence journal was written on-chain.' },
	pause: { title: 'Contract paused', who: 'guardian', meaning: 'Emergency stop: no step can run until the admin resumes.' },
	unpause: { title: 'Contract resumed', who: 'admin', meaning: 'The admin lifted the emergency stop.' },
	proposeWhitelist: { title: 'Supplier change proposed', who: 'admin', meaning: 'Starts the whitelist timelock (double signature required).' },
	applyWhitelist: { title: 'Supplier change applied', who: 'admin', meaning: 'Whitelist change applied after the timelock.' },
	registerDafKey: { title: 'DAF badge key registered', who: 'admin', meaning: 'P-256 public key of the DAF role (TROPIC01 slot).' },
	registerStockKey: { title: 'STOCK badge key registered', who: 'admin', meaning: 'P-256 public key of the STOCK role (TROPIC01 slot).' },
	registerDuressKey: { title: 'Duress key registered', who: 'admin', meaning: 'Second PIN key: pays from the capped parallel wallet.' }
};

export const FLAG_REASONS: [number, string][] = [
	[1 << 2, 'new beneficiary'],
	[1 << 3, 'external origin'],
	[1 << 4, 'atypical amount'],
	[1 << 5, 'hidden instruction flagged'],
	[1 << 6, 'address changed']
];

export type Intent = {
	version: number; algorithm: number; reqId: number; beneficiary: string; token: number;
	amount: string; nonce: number; deadline: number; quoteHash: string; flags: number;
	policy: number; role: 'STOCK' | 'DAF' | 'UNSET' | 'RESERVED'; reasons: string[];
};

/** The 79-byte canonical intent (proto/SPEC.md): what the badge displays and signs. */
export function decodeIntent(hex: string): Intent | null {
	const h = hex.startsWith('0x') ? hex.slice(2) : hex;
	if (h.length !== 79 * 2) return null;
	const b = (o: number, n: number) => h.slice(o * 2, (o + n) * 2);
	const num = (o: number, n: number) => parseInt(b(o, n), 16);
	const flags = num(75, 2);
	return {
		version: num(0, 1),
		algorithm: num(1, 1),
		reqId: num(2, 4),
		beneficiary: getAddress('0x' + b(6, 20)),
		token: num(26, 1),
		amount: BigInt('0x' + b(27, 8)).toString(),
		nonce: num(35, 4),
		deadline: num(39, 4),
		quoteHash: '0x' + b(43, 32),
		flags,
		policy: num(77, 2),
		role: (['UNSET', 'STOCK', 'DAF', 'RESERVED'] as const)[flags & 3],
		reasons: FLAG_REASONS.filter(([bit]) => flags & bit).map(([, r]) => r)
	};
}

export type Call = { fn: string; args: Record<string, any>; intent?: Intent | null; signature?: { r: string; s: string } };

export function decodeCall(data?: string | null): Call | null {
	if (!data || data === '0x') return null;
	try {
		const tx = IFACE.parseTransaction({ data });
		if (!tx) return null;
		const args: Record<string, any> = {};
		tx.fragment.inputs.forEach((inp, i) => (args[inp.name] = typeof tx.args[i] === 'bigint' ? tx.args[i].toString() : tx.args[i]));
		const raw = args.intent ?? args.stockIntent ?? args.dafIntent;
		return {
			fn: tx.name,
			args,
			intent: raw ? decodeIntent(raw) : undefined,
			signature: args.r ? { r: args.r, s: args.s } : undefined
		};
	} catch {
		return null;
	}
}

export function money(units?: string | number | bigint | null, symbol = TOKEN.symbol): string {
	if (units == null) return '—';
	const v = Number(BigInt(units)) / 10 ** TOKEN.decimals;
	return `${v.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })} ${symbol}`;
}

export const short = (h?: string | null, a = 6, b = 4) => (!h ? '' : h.length <= a + b + 2 ? h : `${h.slice(0, a + 2)}…${h.slice(-b)}`);

export function duration(ms?: number | null): string {
	if (ms == null) return '—';
	const s = Math.round(ms / 1000);
	return s < 60 ? `${s} s` : `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, '0')} s`;
}
