import type { PageServerLoad } from './$types';
import api from '$lib/server/api';
import { describeTx } from '$lib/server/lastword';

export const load: PageServerLoad = async ({ params }) => {
	try {
		const entity = await api.resolveEntity(params.hash, true);
		if (entity.kind === 'tx') {
			return {
				tx: entity.data,
				lastword: await describeTx(entity.data).catch(() => null)
			};
		} else {
			return { tx: null, lastword: null };
		}
	} catch {
		return { tx: null, lastword: null };
	}
};
