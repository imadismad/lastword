import { decodeCall } from '$lib/lastword';

export const getTransactionMethod = (tx: any) => {
	// LASTWORD calls are decoded locally (the public signature lookup is disabled)
	const lw = decodeCall(tx?.data ?? tx?.input);
	if (lw) return lw.fn;
	return tx?.method?.indexOf('(') >= 0
		? tx?.method?.split('(').shift()
		: tx?.method?.trim() === '0x'
			? null
			: tx.method;
};