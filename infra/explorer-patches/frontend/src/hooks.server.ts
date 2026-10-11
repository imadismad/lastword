import { DB_STRING, DB_NAME } from '$env/static/private';
import mongoose from 'mongoose';

let connection: mongoose.Mongoose | null = null;
let lastAttempt = 0;

export async function handle({ resolve, event }) {
	// Database: optional. Pages read the explorer API and the chain; only a few legacy
	// widgets use Mongo directly. If it is down, keep serving and retry every 30 s
	// instead of failing every request.
	if ((!connection || connection.connection.readyState !== 1) && Date.now() - lastAttempt > 30_000) {
		lastAttempt = Date.now();
		try {
			connection = (await mongoose.connect(
				DB_STRING as string,
				{
					dbName: DB_NAME,
					bufferCommands: false,
					socketTimeoutMS: 2000,
					serverSelectionTimeoutMS: 2000
				} as mongoose.ConnectOptions
			)) as mongoose.Mongoose;
		} catch {
			console.error('> Database unavailable — serving from the API and the chain only');
		}
	}
	return resolve(event);
}
