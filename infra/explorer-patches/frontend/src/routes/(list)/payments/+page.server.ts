import type { PageServerLoad } from './$types';
import { payments, summary } from '$lib/server/lastword';

export const load: PageServerLoad = async ({ url }) => {
	const filter = url.searchParams.get('status') ?? 'all';
	try {
		const [list, sum] = await Promise.all([payments(), summary()]);
		return { payments: filter === 'all' ? list : list.filter((p) => p.status === filter), summary: sum, filter };
	} catch (e) {
		return { payments: [], summary: null, filter, error: String(e) };
	}
};
