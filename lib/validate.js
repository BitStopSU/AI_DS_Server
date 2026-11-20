export function validateAction(name, args, guild) {
  if (name === "create_channel" && (!args.name || args.name.length < 2)) return { ok: false, reason: "Имя 2-100" };
  return { ok: true };
}