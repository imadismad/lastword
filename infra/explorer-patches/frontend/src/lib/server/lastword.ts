/**
 * Payment traceability, rebuilt from the chain itself (contract events + calldata), not
 * from any off-chain database: what an auditor would do.
 */
import { JsonRpcProvider, getAddress } from 'ethers';
import { env } from '$env/dynamic/private';
import { env as pub } from '$env/dynamic/public';
import { CONTRACT, IFACE, TOKEN, decodeCall, party, type Intent, type Call } from '$lib/lastword';

const RPC = env.LW_RPC_URL || pub.PUBLIC_RPC_URL;
let provider: JsonRpcProvider | null = null;
const rpc = () => (provider ??= new JsonRpcProvider(RPC, undefined, { staticNetwork: true }));

export type Step = { tx: string; block: number; ts: number; from: string; signature?: { r: string; s: string } };
export type Payment = {
	reqId: number;
	status: 'proposed' | 'attested' | 'paid' | 'refused' | 'cancelled' | 'expired';
	supplier: string | null;
	suspended?: boolean;
	beneficiary: string;
	amount: string;
	deadline: number;
	quoteHash: string;
	reasons: string[];
	policy: number;
	digest?: string;
	proposed?: Step;
	attested?: Step;
	approved?: Step;
	refused?: Step & { reason: number };
	cancelled?: Step;
	transfer?: { from: string; to: string; value: string; tx: string };
	durationMs?: number;
};

const blockTs = new Map<number, number>();
async function ts(block: number) {
	if (!blockTs.has(block)) blockTs.set(block, (await rpc().getBlock(block))?.timestamp ?? 0);
	return blockTs.get(block)!;
}

let cache: { at: number; data: Payment[] } | null = null;

export async function payments(maxAgeMs = 4000): Promise<Payment[]> {
	if (cache && Date.now() - cache.at < maxAgeMs) return cache.data;
	const p = rpc();
	const logs = await p.getLogs({ address: CONTRACT, fromBlock: 0, toBlock: 'latest' });
	const byReq = new Map<number, Payment>();
	const txCache = new Map<string, Call | null>();
	const call = async (hash: string) => {
		if (!txCache.has(hash)) txCache.set(hash, decodeCall((await p.getTransaction(hash))?.data));
		return txCache.get(hash)!;
	};

	for (const log of logs) {
		let ev;
		try {
			ev = IFACE.parseLog(log);
		} catch {
			continue;
		}
		if (!ev || ev.args.reqId === undefined) continue;
		const reqId = Number(ev.args.reqId);
		const tx = await p.getTransaction(log.transactionHash);
		const step: Step = { tx: log.transactionHash, block: log.blockNumber, ts: await ts(log.blockNumber), from: tx?.from ?? '' };

		if (ev.name === 'Proposed') {
			const c = await call(log.transactionHash);
			const it = c?.intent as Intent | undefined;
			const who = party(it?.beneficiary);
			byReq.set(reqId, {
				reqId,
				status: 'proposed',
				supplier: who?.name ?? null,
				suspended: who?.suspended,
				beneficiary: it?.beneficiary ?? '',
				amount: it?.amount ?? '0',
				deadline: it?.deadline ?? 0,
				quoteHash: it?.quoteHash ?? '',
				reasons: it?.reasons ?? [],
				policy: it?.policy ?? 0,
				digest: ev.args.digest,
				proposed: step
			});
			continue;
		}
		const pay = byReq.get(reqId);
		if (!pay) continue;
		if (ev.name === 'Attested') {
			pay.attested = { ...step, signature: (await call(log.transactionHash))?.signature };
			pay.status = 'attested';
		} else if (ev.name === 'Approved') {
			pay.approved = { ...step, signature: (await call(log.transactionHash))?.signature };
			pay.status = 'paid';
			pay.transfer = await fundsMoved(log.transactionHash);
		} else if (ev.name === 'Refused') {
			pay.refused = { ...step, reason: Number(ev.args.reason) };
			pay.status = 'refused';
		} else if (ev.name === 'Cancelled') {
			pay.cancelled = step;
			pay.status = 'cancelled';
		}
	}
	const list = [...byReq.values()].sort((a, b) => (b.proposed?.block ?? 0) - (a.proposed?.block ?? 0));
	const now = Date.now() / 1000;
	for (const x of list) {
		// the contract refuses any step after the deadline (C8): an unfinished request is dead
		if ((x.status === 'proposed' || x.status === 'attested') && x.deadline && x.deadline < now) x.status = 'expired';
		const end = x.approved ?? x.refused ?? x.cancelled;
		if (end && x.proposed) x.durationMs = (end.ts - x.proposed.ts) * 1000;
	}
	cache = { at: Date.now(), data: list };
	return list;
}

/** The ERC-20 transfer the payment actually produced (vault -> supplier). */
async function fundsMoved(hash: string) {
	const rc = await rpc().getTransactionReceipt(hash);
	for (const l of rc?.logs ?? []) {
		if (getAddress(l.address) !== TOKEN.address) continue;
		try {
			const ev = IFACE.parseLog(l);
			if (ev?.name === 'Transfer')
				return { from: ev.args.from, to: ev.args.to, value: ev.args.value.toString(), tx: hash };
		} catch {
			/* not a transfer */
		}
	}
	return undefined;
}

export async function payment(reqId: number) {
	return (await payments()).find((p) => p.reqId === reqId) ?? null;
}

/** For the transaction page: what this LASTWORD call means, and the payment it belongs to. */
export async function describeTx(tx: any) {
	if (!tx?.to) return null;
	try {
		if (getAddress(tx.to) !== CONTRACT) return null;
	} catch {
		return null;
	}
	const call = decodeCall(tx.data);
	if (!call) return null;
	const reqId = call.intent?.reqId ?? (call.args.reqId != null ? Number(call.args.reqId) : null);
	return { call, payment: reqId != null ? await payment(reqId) : null };
}

export async function summary() {
	const list = await payments();
	const paid = list.filter((p) => p.status === 'paid');
	const volume = paid.reduce((s, p) => s + BigInt(p.amount), 0n);
	const durations = paid.map((p) => p.durationMs ?? 0).filter(Boolean);
	return {
		total: list.length,
		paid: paid.length,
		pending: list.filter((p) => p.status === 'proposed' || p.status === 'attested').length,
		volume: volume.toString(),
		suppliers: new Set(paid.map((p) => p.beneficiary)).size,
		medianMs: durations.length ? durations.sort((a, b) => a - b)[Math.floor(durations.length / 2)] : null,
		latest: list.slice(0, 6)
	};
}
