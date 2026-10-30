import { Pool } from 'pg';
const globalDb = globalThis as unknown as { vehiclePool?: Pool };
export const pool = globalDb.vehiclePool ?? new Pool({ connectionString: process.env.DATABASE_URL, max: 8, connectionTimeoutMillis: 3000, statement_timeout: 5000, options: '-c default_transaction_read_only=on' });
if (process.env.NODE_ENV !== 'production') globalDb.vehiclePool = pool;
