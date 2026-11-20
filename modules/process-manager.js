import { startBot, stopBot, restartBot, getStatus, autoStartAll, startWatchdog } from "../core/process-manager.js";

export default {
  id: "process-manager",
  name: "Управление ботами",
  description: "Запуск, остановка, перезапуск Python-ботов",
  defaultEnabled: true,

  startBot,
  stopBot,
  restartBot,
  getStatus,
  autoStartAll,
  startWatchdog,
};