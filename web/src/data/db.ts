// DuckDB-WASM singleton. The engine and data load once, on first use, and every
// page shares the same connection. Files are served next to the site (no CDN), so
// moving hosts only means changing VITE_BASE.
import * as duckdb from "@duckdb/duckdb-wasm";
import ehWorker from "@duckdb/duckdb-wasm/dist/duckdb-browser-eh.worker.js?url";
import mvpWorker from "@duckdb/duckdb-wasm/dist/duckdb-browser-mvp.worker.js?url";
import ehWasm from "@duckdb/duckdb-wasm/dist/duckdb-eh.wasm?url";
import mvpWasm from "@duckdb/duckdb-wasm/dist/duckdb-mvp.wasm?url";

const BUNDLES: duckdb.DuckDBBundles = {
  mvp: { mainModule: mvpWasm, mainWorker: mvpWorker },
  eh: { mainModule: ehWasm, mainWorker: ehWorker },
};

const TABLES = ["games", "game_tags", "combos"] as const;

export function dataUrl(file: string): string {
  return new URL(`${import.meta.env.BASE_URL}data/${file}`, window.location.href).href;
}

let connection: Promise<duckdb.AsyncDuckDBConnection> | null = null;

async function init(): Promise<duckdb.AsyncDuckDBConnection> {
  const bundle = await duckdb.selectBundle(BUNDLES);
  const worker = new Worker(bundle.mainWorker!);
  const db = new duckdb.AsyncDuckDB(new duckdb.VoidLogger(), worker);
  await db.instantiate(bundle.mainModule, bundle.pthreadWorker);
  const conn = await db.connect();
  await Promise.all(
    TABLES.map(async (t) => {
      const res = await fetch(dataUrl(`${t}.parquet`));
      if (!res.ok) throw new Error(`Failed to load ${t}.parquet (${res.status})`);
      await db.registerFileBuffer(`${t}.parquet`, new Uint8Array(await res.arrayBuffer()));
    }),
  );
  for (const t of TABLES) {
    await conn.query(`CREATE TABLE ${t} AS SELECT * FROM read_parquet('${t}.parquet')`);
  }
  return conn;
}

export function getConnection(): Promise<duckdb.AsyncDuckDBConnection> {
  if (!connection) {
    connection = init().catch((e) => {
      connection = null; // allow a retry
      throw e;
    });
  }
  return connection;
}

/** Run a query and return plain JS rows (columns must not be BIGINT; cast in SQL). */
export async function query<T>(sql: string): Promise<T[]> {
  const conn = await getConnection();
  const table = await conn.query(sql);
  return table.toArray().map((row) => row.toJSON() as T);
}
