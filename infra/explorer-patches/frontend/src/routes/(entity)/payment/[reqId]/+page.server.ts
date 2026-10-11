import type { PageServerLoad } from './$types';
import { error } from '@sveltejs/kit';
import { payment } from '$lib/server/lastword';

export const load: PageServerLoad = async ({ params }) => {
	const reqId = Number(params.reqId);
	if (!Number.isInteger(reqId) || reqId < 0) throw error(404, 'Unknown payment');
	const p = await payment(reqId);
	if (!p) throw error(404, `No LASTWORD payment #${reqId} on this chain`);
	return { p };
};
