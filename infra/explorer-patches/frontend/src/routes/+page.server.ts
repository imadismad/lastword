import type { PageServerLoad } from './$types';
import api from '$lib/server/api';
import { summary } from '$lib/server/lastword';

export const load: PageServerLoad = async () => {
	const lastword = await summary().catch(() => null);
	try {
		return {
			lastword,
			latestBlocks: await api.getBlocks(),
			latestTxs: await api.getTransactions().then((res) => res.transactions),
			latestTxsChart: await api.getTransactionsChart({ days: 30 }),
			txsCount: await api.countTransactions()
		};
	} catch {
		return {
			apiError: true,
			lastword,
			latestBlocks: [],
			latestTxs: [],
			latestTxsChart: [],
			txsCount: 0
		};
	}
};
