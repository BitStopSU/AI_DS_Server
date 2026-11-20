import fs from "node:fs"; import path from "node:path"; import { fileURLToPath, pathToFileURL } from "node:url"; import { getDb } from "../db/init.js";
const __dirname = path.dirname(fileURLToPath(import.meta.url)); const MODULES_DIR = path.join(__dirname, "..", "modules"); const registry = new Map();

export async function loadModules() { 
  if (!fs.existsSync(MODULES_DIR)) return; 
  for (const file of fs.readdirSync(MODULES_DIR).filter(f => f.endsWith(".js"))) { 
    try { 
      const mod = await import(pathToFileURL(path.join(MODULES_DIR, file)).href); 
      const m = mod.default; 
      if (!m?.id) continue; 
      registry.set(m.id, m); 
      const db = getDb(); 
      const exists = db.prepare("SELECT id FROM modules WHERE id = ?").get(m.id); 
      if (!exists) db.prepare("INSERT INTO modules (id, enabled) VALUES (?, ?)").run(m.id, m.defaultEnabled ? 1 : 0); 
    } catch (err) { console.error("Ошибка загрузки модуля:", file, err.message); } 
  } 
}
export function isEnabled(id) { const row = getDb().prepare("SELECT enabled FROM modules WHERE id = ?").get(id); return !!row?.enabled; }
export function setEnabled(id, enabled) { getDb().prepare("INSERT INTO modules (id, enabled, updated_at) VALUES (?, ?, datetime('now')) ON CONFLICT(id) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at").run(id, enabled ? 1 : 0); }
export function getAllModules() { const rows = getDb().prepare("SELECT id, enabled FROM modules").all(); const stateMap = Object.fromEntries(rows.map(r => [r.id, !!r.enabled])); return [...registry.values()].map(m => ({ id: m.id, name: m.name || m.id, description: m.description || "", enabled: stateMap[m.id] ?? !!m.defaultEnabled })); }
export function getModule(id) { return registry.get(id) || null; }